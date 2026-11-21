#!/usr/bin/env python3
"""Refuse workbench ingest. This skill no longer submits candidates or reads its jobs."""

from __future__ import annotations

import sys


MESSAGE = (
    "天才职业顾问不再读取或投递工作台岗位，也不再把材料交给 Grok Bot。"
    "请继续使用已确认的外部招聘渠道。"
)


if __name__ == "__main__":
    print(MESSAGE, file=sys.stderr)
    raise SystemExit(2)
