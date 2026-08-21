#!/usr/bin/env python3
"""Prepare and, after consent, deliver a privacy-safe job-source suggestion."""

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_STATE = Path(".fanhan-job-agent/source-suggestion.json")
DEFAULT_QUEUE = Path(".fanhan-job-agent/source-suggestions.jsonl")
# ponytail: Zeabur HTTPS is provisioning; switch back to the generated domain once its certificate is active.
DEFAULT_ENDPOINT = "http://43.153.211.45:31807/source-feedback"


def valid_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("网站 URL 必须是完整的 http/https 地址")
    return value.strip()


def fingerprint(payload: dict) -> str:
    stable = {key: payload.get(key, "") for key in ("name", "url", "intro", "note")}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def prepare(name: str, url: str, intro: str, note: str, output: Path) -> dict:
    payload = {
        "schema_version": 1,
        "status": "awaiting_consent",
        "name": name.strip(),
        "url": valid_url(url),
        "intro": intro.strip(),
        "note": note.strip(),
        "privacy": "仅分享网站信息，不包含候选人姓名、联系方式、简历、求职偏好或登录信息。",
    }
    if not payload["name"]:
        raise ValueError("网站名称不能为空")
    payload["fingerprint"] = fingerprint(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def deliver(state: Path, confirmed: bool, endpoint: str, queue: Path) -> dict:
    if not confirmed:
        raise ValueError("未获得用户明确授权，禁止发送")
    payload = json.loads(state.read_text(encoding="utf-8"))
    if payload.get("status") != "awaiting_consent" or payload.get("fingerprint") != fingerprint(payload):
        raise ValueError("来源建议内容已变化，请重新展示并取得授权")
    submission = {key: payload[key] for key in ("schema_version", "name", "url", "intro", "note", "fingerprint")}
    submission["submitted_at"] = datetime.now(timezone.utc).isoformat()
    if endpoint:
        request = urllib.request.Request(valid_url(endpoint), data=json.dumps(submission, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
        token = os.environ.get("FANHAN_SOURCE_FEEDBACK_TOKEN", "").strip()
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"来源反馈接口返回 {response.status}")
        status = "sent"
    else:
        queue.parent.mkdir(parents=True, exist_ok=True)
        with queue.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**submission, "delivery_status": "pending_configuration"}, ensure_ascii=False) + "\n")
        status = "pending_configuration"
    payload["status"] = status
    state.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"delivery_status": status, "queue_path": str(queue) if status != "sent" else ""}


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state, queue = root / "state.json", root / "queue.jsonl"
        payload = prepare("新网站", "https://jobs.example", "AI 岗位", "用户主动推荐", state)
        assert "候选人" not in json.dumps({key: payload[key] for key in ("name", "url", "intro", "note")}, ensure_ascii=False)
        try:
            deliver(state, False, "", queue)
            raise AssertionError("未授权建议不应发送")
        except ValueError:
            pass
        assert deliver(state, True, "", queue)["delivery_status"] == "pending_configuration"
        assert queue.read_text(encoding="utf-8").count("https://jobs.example") == 1
    print("source_feedback self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("--name", required=True)
    create.add_argument("--url", required=True)
    create.add_argument("--intro", default="")
    create.add_argument("--note", default="")
    create.add_argument("--output", type=Path, default=DEFAULT_STATE)
    send = commands.add_parser("send")
    send.add_argument("--state", type=Path, default=DEFAULT_STATE)
    send.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    send.add_argument("--endpoint", default=os.environ.get("FANHAN_SOURCE_FEEDBACK_URL", DEFAULT_ENDPOINT))
    send.add_argument("--confirmed", action="store_true", required=True)
    commands.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    elif args.command == "prepare":
        print(json.dumps(prepare(args.name, args.url, args.intro, args.note, args.output), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(deliver(args.state, args.confirmed, args.endpoint.strip(), args.queue), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
