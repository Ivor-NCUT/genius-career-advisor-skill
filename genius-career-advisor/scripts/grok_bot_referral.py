#!/usr/bin/env python3
"""Refuse Grok Bot referral. This skill no longer sends candidate materials there."""

from __future__ import annotations

import sys


MESSAGE = (
    "天才职业顾问不再读取或投递工作台岗位，也不再把材料交给 Grok Bot。"
    "请继续使用已确认的外部招聘渠道。"
)


def main() -> None:
    if "--self-test" in sys.argv[1:] or "self-test" in sys.argv[1:]:
        print("grok_bot_referral self-test: ok")
        return
    print(MESSAGE, file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
