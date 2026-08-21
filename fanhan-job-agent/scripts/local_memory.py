#!/usr/bin/env python3
"""Create the two local Markdown memory files without overwriting user data."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path


USER_MEMORY = """# 用户求职记忆

> 只记录候选人明确确认的求职偏好；未知信息保持未知，不从简历或当前位置推断。

## 当前求职目标

- 目标岗位：未知
- 意向城市／办公方式：未知
- 工作类型：未知
- 最早到岗时间：未知

## 公司与渠道偏好

- 偏好行业／公司类型：未知
- 明确排除项：未知
- 已确认优先查询的网站：未知

## 本轮找岗笔记

- 暂无
"""

AGENT_MEMORY = """# Agent 平台执行记忆

> 只记录招聘平台的技术事实、失败路径和已验证解决办法；禁止写入候选人姓名、联系方式、简历正文、Cookie、Token 或登录凭据。

## 平台记录

每条记录包含：日期、平台、操作、现象、原因、解决办法、验证结果、复用条件。

- 暂无
"""


def ensure(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = (
        directory / "用户求职记忆.md",
        directory / "Agent平台执行记忆.md",
    )
    for path, content in zip(paths, (USER_MEMORY, AGENT_MEMORY)):
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    return paths


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        user_path, agent_path = ensure(Path(directory))
        user_path.write_text("# 用户已修改\n", encoding="utf-8")
        ensure(Path(directory))
        assert user_path.read_text(encoding="utf-8") == "# 用户已修改\n"
        assert "候选人明确确认" in USER_MEMORY
        assert "禁止写入候选人姓名" in agent_path.read_text(encoding="utf-8")
        assert user_path != agent_path
    print("local_memory self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path(".fanhan-job-agent"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    for path in ensure(args.directory):
        print(path)


if __name__ == "__main__":
    main()
