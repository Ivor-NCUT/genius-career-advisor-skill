#!/usr/bin/env python3
"""Keep confirmed application answers and interview practice in one local file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


SCHEMA = "fanhan-candidate-memory-v1"
QUESTION_TYPES = {"experience", "motivation", "behavioral", "process", "tools", "logistics", "other"}
SCORE_FIELDS = ("substance", "structure", "relevance", "credibility", "differentiation")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value)


def required(value: str, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field}_required")
    return value


def evidence(values: list[str]) -> list[str]:
    result = [item.strip() for item in values if item.strip()]
    if not result:
        raise ValueError("evidence_required")
    return list(dict.fromkeys(result))


def empty_memory() -> dict:
    return {"schema_version": SCHEMA, "answers": [], "stories": [], "practice_sessions": []}


def career_local(path: Path) -> Path:
    path = path.expanduser().resolve()
    if ".fanhan-job-agent" not in path.parts:
        raise ValueError("candidate_memory_must_be_local")
    return path


def load(path: Path) -> dict:
    if not path.exists():
        return empty_memory()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SCHEMA:
        raise ValueError("candidate_memory_schema_mismatch")
    for field in ("answers", "stories", "practice_sessions"):
        if not isinstance(value.get(field), list):
            raise ValueError(f"candidate_memory_{field}_invalid")
    return value


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def stable_id(prefix: str, *parts: str) -> str:
    source = "|".join(normalized(part) for part in parts).encode()
    return f"{prefix}-{hashlib.sha256(source).hexdigest()[:16]}"


def add_answer(memory: dict, args: argparse.Namespace) -> dict:
    if not args.confirmed:
        raise ValueError("answer_confirmation_required")
    question_type = required(args.question_type, "question_type")
    if question_type not in QUESTION_TYPES:
        raise ValueError("question_type_invalid")
    question = required(args.question, "question")
    company = required(args.company, "company")
    job_title = required(args.job_title, "job_title")
    answer_id = stable_id("answer", company, job_title, question)
    previous = next((item for item in memory["answers"] if item.get("id") == answer_id), None)
    record = {
        "id": answer_id,
        "question": question,
        "normalized_question": normalized(question),
        "question_type": question_type,
        "answer": required(args.answer, "answer"),
        "company": company,
        "job_title": job_title,
        "evidence": evidence(args.evidence),
        "confirmed": True,
        "created_at": previous.get("created_at") if previous else now(),
        "updated_at": now(),
        "usage_count": int(previous.get("usage_count", 0)) + 1 if previous else 1,
    }
    memory["answers"] = [item for item in memory["answers"] if item.get("id") != answer_id]
    memory["answers"].append(record)
    return record


def similarity(left: str, right: str) -> float:
    left, right = normalized(left), normalized(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    sequence = SequenceMatcher(None, left, right).ratio()
    left_tokens, right_tokens = set(left), set(right)
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return max(sequence, overlap)


def find_answers(memory: dict, question: str, limit: int) -> list[dict]:
    ranked = []
    for answer in memory["answers"]:
        score = similarity(question, answer.get("question", ""))
        if score >= 0.45:
            ranked.append(dict(answer, similarity=round(score, 3)))
    return sorted(ranked, key=lambda item: (item["similarity"], item["updated_at"]), reverse=True)[:limit]


def add_story(memory: dict, args: argparse.Namespace) -> dict:
    if not args.confirmed:
        raise ValueError("story_confirmation_required")
    title = required(args.title, "title")
    story_id = stable_id("story", title)
    previous = next((item for item in memory["stories"] if item.get("id") == story_id), None)
    record = {
        "id": story_id,
        "title": title,
        "situation": required(args.situation, "situation"),
        "task": required(args.task, "task"),
        "action": required(args.action, "action"),
        "result": required(args.result, "result"),
        "evidence": evidence(args.evidence),
        "question_types": list(dict.fromkeys(item.strip() for item in args.question_type if item.strip())),
        "confirmed": True,
        "created_at": previous.get("created_at") if previous else now(),
        "updated_at": now(),
    }
    memory["stories"] = [item for item in memory["stories"] if item.get("id") != story_id]
    memory["stories"].append(record)
    return record


def record_practice(memory: dict, args: argparse.Namespace) -> dict:
    scores = {field: getattr(args, field) for field in SCORE_FIELDS}
    if any(not 1 <= score <= 5 for score in scores.values()):
        raise ValueError("practice_score_must_be_1_to_5")
    record = {
        "id": stable_id("practice", now(), args.company, args.job_title, args.question),
        "company": required(args.company, "company"),
        "job_title": required(args.job_title, "job_title"),
        "question": required(args.question, "question"),
        "answer_summary": required(args.answer_summary, "answer_summary"),
        "scores": scores,
        "what_worked": required(args.what_worked, "what_worked"),
        "priority_move": required(args.priority_move, "priority_move"),
        "created_at": now(),
    }
    memory["practice_sessions"].append(record)
    return record


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--path", type=Path, default=Path(".fanhan-job-agent/candidate-memory.json"))
    commands = value.add_subparsers(dest="command", required=True)

    answer = commands.add_parser("add-answer")
    answer.add_argument("--question", required=True)
    answer.add_argument("--question-type", required=True, choices=sorted(QUESTION_TYPES))
    answer.add_argument("--answer", required=True)
    answer.add_argument("--company", required=True)
    answer.add_argument("--job-title", required=True)
    answer.add_argument("--evidence", action="append", default=[])
    answer.add_argument("--confirmed", action="store_true")

    find = commands.add_parser("find-answer")
    find.add_argument("--question", required=True)
    find.add_argument("--limit", type=int, default=3)

    story = commands.add_parser("add-story")
    story.add_argument("--title", required=True)
    for field in ("situation", "task", "action", "result"):
        story.add_argument(f"--{field}", required=True)
    story.add_argument("--evidence", action="append", default=[])
    story.add_argument("--question-type", action="append", default=[])
    story.add_argument("--confirmed", action="store_true")

    practice = commands.add_parser("record-practice")
    practice.add_argument("--company", required=True)
    practice.add_argument("--job-title", required=True)
    practice.add_argument("--question", required=True)
    practice.add_argument("--answer-summary", required=True)
    for field in SCORE_FIELDS:
        practice.add_argument(f"--{field.replace('_', '-')}", type=int, required=True)
    practice.add_argument("--what-worked", required=True)
    practice.add_argument("--priority-move", required=True)

    commands.add_parser("show")
    commands.add_parser("self-test")
    return value


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "candidate-memory.json"
        memory = load(path)
        answer_args = argparse.Namespace(
            confirmed=True, question="为什么想加入我们？", question_type="motivation",
            answer="因为岗位与我的真实项目经历一致。", company="Example", job_title="PM",
            evidence=["职业经历.md#项目A"],
        )
        first = add_answer(memory, answer_args)
        save(path, memory)
        answer_args.answer = "因为该岗位与我负责的 Agent 项目一致。"
        second = add_answer(memory, answer_args)
        save(path, memory)
        assert first["id"] == second["id"] and len(load(path)["answers"]) == 1
        assert find_answers(load(path), "为什么希望加入这家公司", 3)[0]["id"] == first["id"]

        story_args = argparse.Namespace(
            confirmed=True, title="从零搭建 Agent 测试流程", situation="项目缺少验收流程",
            task="建立可复现测试", action="拆解链路并补齐自动检查", result="缩短验收时间",
            evidence=["职业经历.md#Agent测试"], question_type=["项目经历", "解决困难"],
        )
        add_story(memory, story_args)
        practice_args = argparse.Namespace(
            company="Example", job_title="PM", question="讲一个项目经历",
            answer_summary="介绍了 Agent 测试项目", substance=4, structure=3, relevance=5,
            credibility=4, differentiation=3, what_worked="证据具体", priority_move="补充量化结果",
        )
        record_practice(memory, practice_args)
        save(path, memory)
        stored = load(path)
        assert len(stored["stories"]) == 1 and len(stored["practice_sessions"]) == 1
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    print("candidate_memory self-test: ok")


def main() -> None:
    args = parser().parse_args()
    if args.command == "self-test":
        self_test()
        return
    args.path = career_local(args.path)
    if args.command == "find-answer":
        if args.limit < 1:
            raise SystemExit("limit must be positive")
        print(json.dumps(find_answers(load(args.path), args.question, args.limit), ensure_ascii=False, indent=2))
        return
    memory = load(args.path)
    if args.command == "add-answer":
        result = add_answer(memory, args)
    elif args.command == "add-story":
        result = add_story(memory, args)
    elif args.command == "record-practice":
        result = record_practice(memory, args)
    else:
        print(json.dumps(memory, ensure_ascii=False, indent=2))
        return
    save(args.path, memory)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
