#!/usr/bin/env python3
"""Check explicit candidate constraints before sending material to Workbench."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from pathlib import Path


UNKNOWN = {"", "unknown", "未知"}


def text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().lower()


def known(value: object) -> bool:
    return text(value) not in UNKNOWN


def employment(value: object) -> str:
    value = text(value)
    intern = bool(re.search(r"实习|intern", value))
    full_time = bool(re.search(r"全职|正职|full.?time", value))
    if intern and full_time:
        return "either"
    if intern:
        return "internship"
    if full_time:
        return "full_time"
    return value if value in {"internship", "full_time", "either"} else "unknown"


def location(value: object) -> str:
    value = text(value)
    return value[:-1] if value.endswith("市") else value


def work_mode(value: object) -> str:
    value = text(value)
    if re.search(r"远程|remote", value):
        return "remote"
    if re.search(r"混合|hybrid", value):
        return "hybrid"
    if re.search(r"到岗|现场|线下|on.?site", value):
        return "on_site"
    return "unknown"


def iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(text(value)[:10])
    except ValueError:
        return None


def evaluate(profile: dict, job: dict) -> dict:
    if profile.get("schema_version") != "fanhan-career-profile-v1":
        raise ValueError("schema_version 必须是 fanhan-career-profile-v1")

    intent = profile.get("intent", {})
    conflicts: list[dict[str, str]] = []
    unknowns: list[str] = []

    candidate_type = employment(intent.get("employment_type"))
    job_type = employment(job.get("work_type"))
    if "unknown" in {candidate_type, job_type}:
        unknowns.append("employment_type")
    elif candidate_type != "either" and job_type != "either" and candidate_type != job_type:
        conflicts.append({"field": "employment_type", "reason": "候选人的实习／正职选择与岗位不一致"})

    preferred = {location(item) for item in intent.get("preferred_locations", []) if known(item)}
    job_city = location(job.get("city"))
    if not preferred or not known(job_city):
        unknowns.append("location")
    elif not preferred.intersection({"不限", "anywhere", "any"}) and job_city not in preferred:
        conflicts.append({"field": "location", "reason": "岗位城市不在候选人明确接受的地点中"})

    remote = intent.get("remote_preference")
    mode = work_mode(job.get("work_mode"))
    if remote not in {"accept", "reject", "conditional"} or mode == "unknown":
        unknowns.append("remote_preference_or_job_work_mode")
    elif remote == "reject" and mode == "remote":
        conflicts.append({"field": "remote_preference", "reason": "候选人明确拒绝远程，但岗位是纯远程"})

    relocation = intent.get("relocation_preference")
    relocation_required = job.get("relocation_required")
    if relocation not in {"accept", "reject", "conditional"} or not isinstance(relocation_required, bool):
        unknowns.append("relocation_preference_or_job_requirement")
    elif relocation == "reject" and relocation_required:
        conflicts.append({"field": "relocation_preference", "reason": "候选人明确不搬迁，但岗位要求搬迁"})

    available = iso_date(intent.get("available_from"))
    required = iso_date(job.get("available_from") or job.get("required_start_date"))
    if not available or not required:
        unknowns.append("availability")
    elif available > required:
        conflicts.append({"field": "available_from", "reason": "候选人可入职日期晚于岗位要求"})

    candidate_auth = intent.get("work_authorization", "unknown")
    job_auth = job.get("work_authorization", "unknown")
    candidate_auth = {text(item) for item in candidate_auth} if isinstance(candidate_auth, list) else set()
    job_auth = {text(item) for item in job_auth} if isinstance(job_auth, list) else set()
    if not candidate_auth or not job_auth:
        unknowns.append("work_authorization")
    elif candidate_auth.isdisjoint(job_auth):
        conflicts.append({"field": "work_authorization", "reason": "候选人的工作许可与岗位要求不一致"})

    unknowns = list(dict.fromkeys(unknowns))
    return {
        "decision": "not_recommended" if conflicts else "needs_review" if unknowns else "eligible_for_scoring",
        "conflicts": conflicts,
        "unknowns": unknowns,
        "score_override": bool(conflicts),
    }


def self_test() -> None:
    profile = {
        "schema_version": "fanhan-career-profile-v1",
        "current_city": "北京",
        "intent": {
            "employment_type": "internship",
            "preferred_locations": ["上海市"],
            "remote_preference": "reject",
            "relocation_preference": "accept",
            "available_from": "2026-09-01",
            "work_authorization": ["中国大陆"],
        },
        "education": {"status": "known", "items": []},
    }
    job = {
        "work_type": "全职", "city": "北京", "score": 99,
        "required_skills": ["不存在的技能"], "education": "博士",
    }
    result = evaluate(profile, job)
    assert result["decision"] == "not_recommended"
    assert result["score_override"] is True
    assert {item["field"] for item in result["conflicts"]} == {"employment_type", "location"}
    assert "remote_preference_or_job_work_mode" in result["unknowns"]
    assert "relocation_preference_or_job_requirement" in result["unknowns"]
    assert "availability" in result["unknowns"]
    assert "work_authorization" in result["unknowns"]
    assert all(item["field"] not in {"education", "required_skills"} for item in result["conflicts"])

    compatible = json.loads(json.dumps(profile, ensure_ascii=False))
    compatible["intent"]["employment_type"] = "full_time"
    compatible["intent"]["preferred_locations"] = ["北京"]
    complete_job = {
        "work_type": "正职", "city": "北京市", "work_mode": "线下",
        "relocation_required": False,
        "required_start_date": "2026-10-01", "work_authorization": ["中国大陆"],
    }
    assert evaluate(compatible, complete_job)["decision"] == "eligible_for_scoring"
    print("match_guard self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", help="职业档案 JSON 路径")
    parser.add_argument("job", nargs="?", help="工作台公开岗位 JSON 路径")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.profile or not args.job:
        parser.error("请提供职业档案和岗位 JSON 路径")
    profile = json.loads(Path(args.profile).expanduser().read_text(encoding="utf-8"))
    job = json.loads(Path(args.job).expanduser().read_text(encoding="utf-8"))
    print(json.dumps(evaluate(profile, job), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
