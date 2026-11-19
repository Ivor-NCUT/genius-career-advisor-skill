#!/usr/bin/env python3
"""Retired. This command no longer uploads candidates or reads application status.

Referral delivery now goes through grok_bot_referral.py. Do not call the old
workbench ingest routes from this skill.
"""

from __future__ import annotations

import sys


MESSAGE = (
    "workbench_client.py 已停用，不再提交候选人材料，也不查询申请或通知状态。"
    "请改用 grok_bot_referral.py 的 preview、record-consent 和 submit。"
)


if __name__ == "__main__":
    print(MESSAGE, file=sys.stderr)
    raise SystemExit(2)
