#!/usr/bin/env python3
"""Resolve the local candidate workspace without moving existing data.

New sessions use `.genius-career-advisor`. A directory that is still named
`.fanhan-job-agent` remains valid, so previously saved profiles, resumes, and
referral state keep working. This command does not create, move, or merge data.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path


PUBLIC_WORKSPACE = ".genius-career-advisor"
LEGACY_WORKSPACE = ".fanhan-job-agent"
WORKSPACE_NAMES = (PUBLIC_WORKSPACE, LEGACY_WORKSPACE)


def is_workspace_name(name: str) -> bool:
    return name in WORKSPACE_NAMES


def workspace_index(parts: tuple[str, ...] | list[str]) -> int | None:
    indexes = [index for index, part in enumerate(parts) if part in WORKSPACE_NAMES]
    if not indexes:
        return None
    return indexes[-1]


def resolve(start: Path | None = None) -> Path:
    """Return the workspace directory to use. Do not create it."""
    root = (start or Path(".")).expanduser().resolve()
    public = root / PUBLIC_WORKSPACE
    legacy = root / LEGACY_WORKSPACE
    if public.is_dir():
        return public
    if legacy.is_dir():
        return legacy
    return public


def describe(start: Path | None = None) -> dict:
    root = (start or Path(".")).expanduser().resolve()
    public = root / PUBLIC_WORKSPACE
    legacy = root / LEGACY_WORKSPACE
    chosen = resolve(root)
    if public.is_dir() and legacy.is_dir():
        active = "public"
        note = (
            "两个工作区都存在。继续使用 .genius-career-advisor，"
            "不要静默合并或覆盖 .fanhan-job-agent。"
        )
    elif public.is_dir():
        active = "public"
        note = "使用公开工作区 .genius-career-advisor。"
    elif legacy.is_dir():
        active = "legacy"
        note = (
            "沿用已有的 .fanhan-job-agent，避免把本地档案拆到新目录。"
            "新的空工作区才使用 .genius-career-advisor。"
        )
    else:
        active = "public"
        note = "还没有本地工作区。请创建 .genius-career-advisor，不要再新建 .fanhan-job-agent。"
    return {
        "directory": chosen.name,
        "path": str(chosen),
        "active": active,
        "public_present": public.is_dir(),
        "legacy_present": legacy.is_dir(),
        "note": note,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        empty = describe(root)
        assert empty["directory"] == PUBLIC_WORKSPACE
        assert empty["active"] == "public"
        assert empty["legacy_present"] is False
        legacy = root / LEGACY_WORKSPACE
        legacy.mkdir()
        (legacy / "profile.json").write_text("{}", encoding="utf-8")
        kept = describe(root)
        assert kept["directory"] == LEGACY_WORKSPACE
        assert kept["active"] == "legacy"
        assert resolve(root) == legacy.resolve()
        public = root / PUBLIC_WORKSPACE
        public.mkdir()
        both = describe(root)
        assert both["directory"] == PUBLIC_WORKSPACE
        assert both["public_present"] and both["legacy_present"]
        assert workspace_index((".genius-career-advisor", "outbox")) == 0
        assert workspace_index(("a", ".fanhan-job-agent", "outbox")) == 1
        assert workspace_index(("nope",)) is None
    print("workspace self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="resolve", choices=("resolve",))
    parser.add_argument("--start", type=Path, default=Path("."))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    print(json.dumps(describe(args.start), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
