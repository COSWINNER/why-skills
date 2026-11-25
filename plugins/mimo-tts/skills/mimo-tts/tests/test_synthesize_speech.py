import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
import wave


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "synthesize_speech.py"
TEXT = "  （平静）门开了。[轻笑]\r\n我们赶上了。  "
INSTRUCTION = "放慢语速，在‘赶上’处适当加重音。"
API_KEY = "local-test-only"
MP3 = bytes.fromhex("ff fb 90 64") + bytes(413)


def wav_bytes():
    with BytesIO() as buffer:
        with wave.open(buffer, "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            audio.writeframes(bytes(480))
        return buffer.getvalue()


WAV = wav_bytes()


class SynthesizeSpeechTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.skill = root / "skill"
        self.script = self.skill / "scripts" / SCRIPT.name
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        self.reference = self.workspace / "voice sample.wav"
        self.reference.write_bytes(WAV)
        self.requests = []
        self.response = None

        case = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                case.requests.append((self.path, self.headers.get("api-key"), body))
                if case.response is None:
                    audio = WAV if body["audio"]["format"] == "wav" else MP3
                    response = {"choices": [{"finish_reason": "stop", "message": {
                        "audio": {"data": base64.b64encode(audio).decode("ascii")},
                    }}]}
                    status, headers = 200, {}
                else:
                    status, headers, response = case.response
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        thread.start()
        self.base_url = f"http://127.0.0.1:{server.server_port}/v1"
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("MIMO_", "PYTHON_DOTENV_DISABLED"))}
        self.env.update(MIMO_API_KEY=API_KEY, MIMO_BASE_URL=self.base_url, NO_PROXY="127.0.0.1")

    def invoke(self, *args, settings=None):
        return subprocess.run(
            [sys.executable, str(self.script), *args], cwd=self.workspace,
            env={**self.env, **(settings or {})}, capture_output=True, text=True, timeout=8,
        )

    def check_saved_audio(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        output = Path(result.stdout.strip())
        self.assertTrue(output.is_absolute())
        self.assertEqual(output.read_bytes(), expected)
        return output

    def test_preset_preserves_text_and_places_direction(self):
        result = self.invoke("preset", "--text", TEXT, "--instruction", INSTRUCTION, "--voice", "茉莉")
        output = self.check_saved_audio(result, WAV)
        self.assertEqual(output.parent, self.workspace / "generation-audio")
        self.assertEqual(output.suffix, ".wav")
        self.assertEqual(self.requests, [("/v1/chat/completions", API_KEY, {
            "model": "mimo-v2.5-tts",
            "messages": [{"role": "user", "content": INSTRUCTION}, {"role": "assistant", "content": TEXT}],
            "audio": {"format": "wav", "voice": "茉莉"},
            "stream": False,
        })])

    def test_design_reads_utf8_file_and_omits_voice(self):
        (self.workspace / "台词.txt").write_bytes(TEXT.encode("utf-8-sig"))
        result = self.invoke("design", "--text-file", "台词.txt", "--instruction", "醇厚的成年女声。",
                             "--output", "clips/成片.mp3")
        self.assertEqual(self.check_saved_audio(result, MP3), self.workspace / "clips" / "成片.mp3")
        self.assertEqual(self.requests[-1][2], {
            "model": "mimo-v2.5-tts-voicedesign",
            "messages": [{"role": "user", "content": "醇厚的成年女声。"},
                         {"role": "assistant", "content": TEXT}],
            "audio": {"format": "mp3"},
            "stream": False,
        })

    def test_clone_sends_reference_audio_with_correct_mime_type(self):
        mp3_path = self.workspace / "second.MP3"
        mp3_path.write_bytes(MP3)
        for file, mime, audio in ((self.reference, "audio/wav", WAV), (mp3_path, "audio/mpeg", MP3)):
            with self.subTest(file=file):
                result = self.invoke("clone", "--text", TEXT, "--reference-audio", str(file), "--format", "mp3")
                self.check_saved_audio(result, MP3)
                self.assertEqual(self.requests[-1][2], {
                    "model": "mimo-v2.5-tts-voiceclone",
                    "messages": [{"role": "assistant", "content": TEXT}],
                    "audio": {"format": "mp3", "voice": f"data:{mime};base64,{base64.b64encode(audio).decode()}"},
                    "stream": False,
                })

    def test_replace_one_model_without_changing_the_other_modes(self):
        modes = {
            "preset": ("mimo-v2.5-tts", [], {"format": "wav", "voice": "mimo_default"}),
            "design": ("mimo-v2.5-tts-voicedesign", ["--instruction", INSTRUCTION], {"format": "wav"}),
            "clone": ("mimo-v2.5-tts-voiceclone", ["--reference-audio", str(self.reference)],
                      {"format": "wav", "voice": "data:audio/wav;base64," + base64.b64encode(WAV).decode()}),
        }
        for changed in modes:
            (self.skill / ".env").write_text(f"MIMO_{changed.upper()}_MODEL=alternate-only\n", encoding="utf-8")
            for mode, (default, options, audio) in modes.items():
                with self.subTest(changed=changed, mode=mode):
                    self.check_saved_audio(self.invoke(mode, "--text", TEXT, *options), WAV)
                    body = self.requests[-1][2]
                    self.assertEqual(body["model"], "alternate-only" if changed == mode else default)
                    self.assertEqual(body["audio"], audio)

    def test_config_precedence_and_model_override(self):
        env_path = self.skill / ".env"
        env_path.write_text(f"MIMO_API_KEY={API_KEY}\nMIMO_BASE_URL={self.base_url}/\n"
                            "MIMO_PRESET_MODEL=dotenv-model\n", encoding="utf-8")
        (self.workspace / ".env").write_text("MIMO_PRESET_MODEL=unrelated-file\n", encoding="utf-8")
        settings = {"MIMO_API_KEY": "discarded-key", "MIMO_BASE_URL": self.base_url + "/wrong",
                    "MIMO_PRESET_MODEL": "process-model"}
        self.check_saved_audio(self.invoke("preset", "--text", TEXT, settings=settings), WAV)
        self.assertEqual(self.requests[-1][:2], ("/v1/chat/completions", API_KEY))
        self.assertEqual(self.requests[-1][2]["model"], "dotenv-model")
        self.check_saved_audio(self.invoke("preset", "--text", TEXT, "--model", "explicit-model",
                                          settings=settings), WAV)
        self.assertEqual(self.requests[-1][2]["model"], "explicit-model")
        env_path.unlink()
        self.check_saved_audio(self.invoke("preset", "--text", TEXT,
                                          settings={"MIMO_PRESET_MODEL": "process-model"}), WAV)
        self.assertEqual(self.requests[-1][2]["model"], "process-model")

    def test_rejects_missing_or_incompatible_inputs_before_request(self):
        cases = (
            (("design", "--text", TEXT), "--instruction"),
            (("design", "--text", TEXT, "--instruction", "  "), "non-whitespace"),
            (("clone", "--text", TEXT), "--reference-audio"),
            (("clone", "--text", TEXT, "--reference-audio", "not-a-sample.flac"), "WAV or MP3"),
            (("preset", "--text-file", "missing.txt"), "UTF-8 text file"),
            (("preset", "--text", "  "), "non-whitespace"),
            (("preset", "--text", TEXT, "--output", "file.wav", "--format", "mp3"), "match --format"),
        )
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
        result = self.invoke("preset", "--text", TEXT, settings={"MIMO_API_KEY": ""})
        self.assertIn("MIMO_API_KEY", result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests, [])

    def test_rejects_reference_over_base64_limit(self):
        with self.reference.open("ab") as reference:
            reference.truncate(7_500_001)
        result = self.invoke("clone", "--text", TEXT, "--reference-audio", str(self.reference))
        self.assertEqual(result.returncode, 1)
        self.assertIn("10 MB", result.stderr)
        self.assertEqual(self.requests, [])

    def test_api_failures_leave_no_file_or_sensitive_diagnostics(self):
        good_data = base64.b64encode(WAV).decode()
        bad_data = base64.b64encode(b"not audio").decode()
        cases = (
            (401, {}, {"error": {"message": API_KEY + TEXT}}, "HTTP 401"),
            (302, {"Location": self.base_url + "/elsewhere"}, {}, "HTTP 302"),
            (200, {}, {"choices": []}, "invalid Base64"),
            (200, {}, {"choices": [{"message": {"audio": {"data": "%%%"}}}]}, "invalid Base64"),
            (200, {}, {"choices": [{"message": {"audio": {"data": bad_data}}}]}, "requested format"),
            (200, {}, {"choices": [{"finish_reason": "length", "message": {
                "audio": {"data": good_data}}}]}, "did not finish"),
        )
        for status, headers, response, expected in cases:
            with self.subTest(expected=expected):
                self.response = (status, headers, response)
                result = self.invoke("preset", "--text", TEXT)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)
                self.assertNotIn(API_KEY, result.stderr)
                self.assertNotIn("门开了", result.stderr)
                self.assertFalse((self.workspace / "generation-audio").exists())
        self.assertEqual(len(self.requests), len(cases))

    def test_explicit_output_does_not_replace_existing_file(self):
        output = self.workspace / "existing.wav"
        output.write_bytes(b"keep me")
        result = self.invoke("preset", "--text", TEXT, "--output", str(output))
        self.assertIn("already exists", result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), b"keep me")
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
