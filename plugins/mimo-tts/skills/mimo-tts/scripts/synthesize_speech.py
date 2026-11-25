#!/usr/bin/env python3
"""Generate a WAV or MP3 file with MiMo's preset, design, or clone mode."""

import argparse
import base64
from http.client import HTTPException
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


MODELS = {
    "preset": ("MIMO_PRESET_MODEL", "mimo-v2.5-tts"),
    "design": ("MIMO_DESIGN_MODEL", "mimo-v2.5-tts-voicedesign"),
    "clone": ("MIMO_CLONE_MODEL", "mimo-v2.5-tts-voiceclone"),
}
DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"
AUDIO_TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg"}
MAX_ENCODED_REFERENCE_BYTES = 10_000_000
MAX_REFERENCE_BYTES = MAX_ENCODED_REFERENCE_BYTES // 4 * 3


class SpeechError(Exception):
    """A diagnostic suitable for printing without revealing the request."""


class NoRedirect(HTTPRedirectHandler):
    """Keep credentials and reference audio at the configured endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    mode_help = {
        "preset": "Use a built-in voice",
        "design": "Design a voice with a written description",
        "clone": "Clone a voice from a local reference recording",
    }
    for mode, help_text in mode_help.items():
        command = modes.add_parser(mode, help=help_text, allow_abbrev=False)
        text = command.add_mutually_exclusive_group(required=True)
        text.add_argument("--text", help="Text to speak, including any audio tags")
        text.add_argument("--text-file", type=Path, help="Read the text from a UTF-8 file")
        command.add_argument("--instruction", required=mode == "design",
                             help="Natural-language direction or voice design description")
        command.add_argument("--model", help="Override the model for this invocation")
        command.add_argument("--format", choices=AUDIO_TYPES,
                             help="Output format (default: infer from --output, otherwise wav)")
        command.add_argument("--output", type=Path, help="Output file path ending in .wav or .mp3")
        if mode == "preset":
            command.add_argument("--voice", default="mimo_default", help="Built-in voice ID")
        if mode == "clone":
            command.add_argument("--reference-audio", required=True, type=Path,
                                 help="Local WAV or MP3 reference recording")
    return parser.parse_args(argv)


def load_config(args):
    try:
        from dotenv import load_dotenv
    except ImportError as error:
        raise SpeechError("Install python-dotenv with: python -m pip install python-dotenv") from error
    try:
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    except (OSError, UnicodeError) as error:
        raise SpeechError("Cannot read the skill's .env as UTF-8.") from error

    api_key = os.getenv("MIMO_API_KEY", "").strip()
    if not api_key or any(not 33 <= ord(character) <= 126 for character in api_key):
        raise SpeechError("Set MIMO_API_KEY to a valid API key.")
    base_url = os.getenv("MIMO_BASE_URL", "").strip() or DEFAULT_BASE_URL
    try:
        url = urlsplit(base_url)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username is not None
                or url.query or url.fragment):
            raise ValueError
    except ValueError as error:
        raise SpeechError("MIMO_BASE_URL must be an HTTP(S) API base URL.") from error
    endpoint = urlunsplit(url._replace(path=url.path.rstrip("/") + "/chat/completions"))

    variable, default = MODELS[args.mode]
    model = args.model if args.model is not None else os.getenv(variable, "").strip() or default
    if not model.strip():
        raise SpeechError("--model must contain a model ID.")
    return endpoint, api_key, model.strip()


def matches_audio_format(data, audio_format):
    if audio_format == "wav":
        return len(data) >= 12 and data[:4] in {b"RIFF", b"RIFX", b"RF64"} and data[8:12] == b"WAVE"
    return len(data) >= 4 and (data.startswith(b"ID3") or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0))


def reference_voice(path):
    audio_format = path.suffix.lower().removeprefix(".")
    try:
        if audio_format not in AUDIO_TYPES or not path.is_file():
            raise SpeechError("--reference-audio must point to a local WAV or MP3 file.")
        with path.open("rb") as file:
            data = file.read(MAX_REFERENCE_BYTES + 1)
    except OSError as error:
        raise SpeechError("Cannot read --reference-audio.") from error
    if len(data) > MAX_REFERENCE_BYTES:
        raise SpeechError("The reference audio exceeds MiMo's 10 MB limit after Base64 encoding.")
    if not matches_audio_format(data, audio_format):
        raise SpeechError("The reference audio content does not match its WAV or MP3 extension.")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{AUDIO_TYPES[audio_format]};base64,{encoded}"


def build_payload(args, model, audio_format):
    text = args.text
    if args.text_file is not None:
        try:
            if not args.text_file.is_file():
                raise SpeechError("--text-file must point to a local UTF-8 text file.")
            text = args.text_file.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise SpeechError("Cannot read --text-file as UTF-8.") from error
    if not text.strip():
        raise SpeechError("Speech text must contain non-whitespace content.")

    messages = []
    if args.instruction is not None:
        if not args.instruction.strip():
            raise SpeechError("--instruction must contain non-whitespace content.")
        messages.append({"role": "user", "content": args.instruction})
    messages.append({"role": "assistant", "content": text})

    audio = {"format": audio_format}
    if args.mode == "preset":
        if not args.voice.strip():
            raise SpeechError("--voice must contain a built-in voice ID.")
        audio["voice"] = args.voice.strip()
    elif args.mode == "clone":
        audio["voice"] = reference_voice(args.reference_audio)
    return {"model": model, "messages": messages, "audio": audio, "stream": False}


def synthesize(endpoint, api_key, payload):
    request = Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "api-key": api_key}, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=180) as response:
            result = json.load(response)
    except HTTPError as error:
        with error:
            raise SpeechError(f"MiMo API returned HTTP {error.code}.") from error
    except (URLError, OSError, HTTPException, ValueError) as error:
        raise SpeechError("Could not read a valid MiMo API response. Check the base URL and connection.") from error

    try:
        choice = result["choices"][0]
        finish_reason = choice.get("finish_reason")
        if finish_reason in ("length", "content_filter"):
            raise SpeechError(f"MiMo did not finish the audio ({finish_reason}).")
        audio = base64.b64decode(choice["message"]["audio"]["data"], validate=True)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        raise SpeechError("MiMo returned missing or invalid Base64 audio.") from error
    if not matches_audio_format(audio, payload["audio"]["format"]):
        raise SpeechError("MiMo returned audio that does not match the requested format.")
    return audio


def output_location(args):
    if args.output is None:
        audio_format = args.format or "wav"
        return Path.cwd() / "generation-audio" / f"{args.mode}-{uuid4().hex}.{audio_format}", audio_format

    extension = args.output.suffix.lower().removeprefix(".")
    if extension not in AUDIO_TYPES or (args.format is not None and args.format != extension):
        raise SpeechError("--output must end in .wav or .mp3 and match --format when specified.")
    output = args.output.absolute()
    if os.path.lexists(output):
        raise SpeechError(f"Output already exists: {output}")
    return output, extension


def save_audio(output, audio):
    temporary = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=output.parent, prefix=".mimo-tts-", delete=False) as file:
            temporary = Path(file.name)
            file.write(audio)
        # Publish the complete file atomically without replacing a concurrent output.
        os.link(temporary, output)
    except FileExistsError as error:
        raise SpeechError(f"Output already exists: {output}") from error
    except OSError as error:
        raise SpeechError(f"Could not save the audio to {output} (OS error {error.errno}).") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    args = parse_args(argv)
    try:
        endpoint, api_key, model = load_config(args)
        output, audio_format = output_location(args)
        payload = build_payload(args, model, audio_format)
        save_audio(output, synthesize(endpoint, api_key, payload))
    except SpeechError as error:
        print(f"MiMo TTS ({args.mode}): {error}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
