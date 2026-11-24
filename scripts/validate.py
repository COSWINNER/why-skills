#!/usr/bin/env python3
"""Validate the marketplace catalogs and their shared plugin packages."""

import argparse
import json
from pathlib import Path
import re
import sys


CATALOGS = {
    "codex": ".agents/plugins/marketplace.json",
    "claude": ".claude-plugin/marketplace.json",
}
MANIFESTS = {
    "codex": ".codex-plugin/plugin.json",
    "claude": ".claude-plugin/plugin.json",
}
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VERSION = re.compile(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}")


def read_object(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"无法读取 {path}：{error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须包含一个 JSON 对象")
    return value


def catalog_entries(catalog, client):
    label = CATALOGS[client]
    plugins = catalog.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        raise ValueError(f"{label} 的 plugins 必须是非空数组")

    entries = {}
    for entry in plugins:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or len(name) > 64 or not NAME.fullmatch(name):
            raise ValueError(f"{label} 包含无效的插件名称 {name!r}")
        if name in entries:
            raise ValueError(f"{label} 重复登记插件 {name}")
        path = f"./plugins/{name}"
        expected = {"source": "local", "path": path} if client == "codex" else path
        if entry.get("source") != expected:
            raise ValueError(f"{label} 的 {name} 必须引用本仓库内的 {path}")
        entries[name] = entry
    return entries


def validate_plugin(directory, entries):
    name = directory.name
    if not directory.is_dir():
        raise ValueError(f"插件目录不存在 {directory}")
    if directory.is_symlink() or any(path.is_symlink() for path in directory.rglob("*")):
        raise ValueError(f"{name} 的资源必须存放在插件目录内")

    codex = read_object(directory / MANIFESTS["codex"])
    claude = read_object(directory / MANIFESTS["claude"])
    for field in ("name", "version", "description"):
        if codex.get(field) != claude.get(field):
            raise ValueError(f"{name} 的双端插件 {field} 不一致")
    version = codex.get("version")
    description = codex.get("description")
    if codex.get("name") != name:
        raise ValueError(f"{name} 的插件清单名称与目录不一致")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError(f"{name} 的插件版本必须使用 x.y.z 格式")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{name} 的插件描述不能为空")
    for client, entry in entries.items():
        if entry.get("version", version) != version:
            raise ValueError(f"{name} 的 {client} 市场版本与插件版本不一致")
        if entry.get("description", description) != description:
            raise ValueError(f"{name} 的 {client} 市场描述与插件描述不一致")

    skill_entries = sorted((directory / "skills").glob("*/SKILL.md"))
    expected_skill = directory / "skills" / name / "SKILL.md"
    if skill_entries != [expected_skill] or not expected_skill.is_file():
        raise ValueError(f"{name} 必须包含唯一的同名技能入口 skills/{name}/SKILL.md")
    return {"name": name, "version": version}


def validate_repository(root):
    catalogs = {client: read_object(root / path) for client, path in CATALOGS.items()}
    market_name = catalogs["codex"].get("name")
    if not isinstance(market_name, str) or not NAME.fullmatch(market_name):
        raise ValueError("Codex 市场名称无效")
    if market_name != catalogs["claude"].get("name"):
        raise ValueError("双端市场名称不一致")

    entries = {client: catalog_entries(catalog, client) for client, catalog in catalogs.items()}
    if entries["codex"].keys() != entries["claude"].keys():
        raise ValueError("双端市场的插件清单不一致")

    plugin_root = root / "plugins"
    if not plugin_root.is_dir() or plugin_root.is_symlink():
        raise ValueError("市场必须包含本地 plugins 目录")
    plugins = []
    for name in sorted(entries["codex"]):
        plugin_entries = {client: client_entries[name] for client, client_entries in entries.items()}
        plugins.append(validate_plugin(plugin_root / name, plugin_entries))
    packaged = {
        path.name for path in plugin_root.iterdir()
        if any((path / manifest).is_file() for manifest in MANIFESTS.values())
    }
    if packaged != entries["codex"].keys():
        raise ValueError("存在尚未登记到双端市场的插件")
    return {"ok": True, "marketplace": market_name, "plugins": plugins}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.repo.resolve())
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
