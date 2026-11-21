#!/usr/bin/env python3
"""Refuse workbench job listing. This skill no longer reads or applies to those jobs."""

from __future__ import annotations

import sys


MESSAGE = (
    "天才职业顾问不再读取或投递工作台岗位，也不再把材料交给 Grok Bot。"
    "请继续使用已确认的外部招聘渠道。"
)


def main() -> None:
    if "--self-test" in sys.argv[1:]:
        assert "Grok Bot" in MESSAGE
        assert "工作台" in MESSAGE
        print("fanhan_open_jobs self-test: ok")
        return
    print(MESSAGE, file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
