#!/usr/bin/env python3
"""Evaluate a local Fanhan career profile without reading or printing resume contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path


UNKNOWN = {"", "unknown", "未知"}
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ENUMS = {
    "intent.employment_type": {"internship", "full_time", "either"},
    "intent.remote_preference": {"accept", "reject", "conditional"},
    "intent.relocation_preference": {"accept", "reject", "conditional"},
}
CONSULTATION_DIMENSIONS = {
    "representative_achievement": "从你现有材料里最能代表实力的一段经历开始：你当时要解决什么问题，最后做成了什么？",
    "personal_contribution": "在这段经历里，哪些关键动作是你亲自负责或推动的？",
    "challenge_and_decision": "过程中最难的约束或取舍是什么？你当时为什么这样判断？",
    "result_evidence": "这件事最后有什么可以验证的结果、数据、反馈或交付物？",
    "learning_and_growth": "这段经历最能说明你后来学会了什么，或你下一次会怎样做得更好？",
}
QUESTIONS = {
    "resume.path": "请提供原始简历文件路径。",
    "identity.name": "你的姓名应该怎样写在申请材料上？",
    "career_document.path": "我先根据你的材料整理一份可长期复用的职业经历主档。",
    "contact": "请提供一个有效邮箱，或电话／微信。",
    "contact.evidence": "请确认联系方式来自简历还是你刚才的明确回答。",
    "intent.target_roles": "你希望投递哪些岗位方向？",
    "intent.employment_type": "你找实习、正职，还是两者都可以？",
    "intent.preferred_locations": "你明确接受哪些工作地点？",
    "intent.remote_preference": "你接受远程、拒绝远程，还是需要视情况而定？",
    "intent.relocation_preference": "你愿意搬迁、明确不搬迁，还是需要视情况而定？",
    "intent.available_from": "你最早什么时候可以入职？",
    "education": "简历中的教育信息是否已完整提取？若没有教育经历，请明确确认。",
    "core_experiences": "简历中的核心工作、实习或项目经历是否已完整提取？若没有，请明确确认。",
    **{f"career_consultation.{key}": value for key, value in CONSULTATION_DIMENSIONS.items()},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def known(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in UNKNOWN
    if isinstance(value, list):
        return any(known(item) for item in value)
    return True


def evidence(profile: dict, field: str) -> bool:
    values = profile.get("evidence", {}).get(field, [])
    return isinstance(values, list) and any(known(item) for item in values)


def resume_exists(profile: dict, base_dir: Path) -> bool:
    value = profile.get("resume", {}).get("path")
    if not known(value):
        return False
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.is_file()


def local_file_exists(profile: dict, section: str, base_dir: Path) -> bool:
    value = profile.get(section, {}).get("path")
    if not known(value):
        return False
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.is_file() and path.stat().st_size > 0


def valid_contact(profile: dict) -> bool:
    contact = profile.get("contact", {})
    email = str(contact.get("email") or "").strip().lower()
    phone = str(contact.get("phone_or_wechat") or "").strip()
    return bool(EMAIL.fullmatch(email) or (known(phone) and len(phone) >= 5))


def contact_has_evidence(profile: dict) -> bool:
    contact = profile.get("contact", {})
    email = str(contact.get("email") or "").strip().lower()
    phone = str(contact.get("phone_or_wechat") or "").strip()
    return bool(
        (EMAIL.fullmatch(email) and evidence(profile, "contact.email"))
        or (known(phone) and len(phone) >= 5 and evidence(profile, "contact.phone_or_wechat"))
    )


def completed_consultation_dimension(value: object) -> bool:
    return bool(
        isinstance(value, dict)
        and value.get("confirmed") is True
        and known(value.get("summary"))
        and isinstance(value.get("evidence"), list)
        and any(known(item) for item in value["evidence"])
    )


def evaluate(profile: dict, base_dir: Path) -> dict:
    if profile.get("schema_version") != "fanhan-career-profile-v1":
        raise ValueError("schema_version 必须是 fanhan-career-profile-v1")

    intent = profile.get("intent", {})
    missing = []
    if not resume_exists(profile, base_dir):
        missing.append("resume.path")
    if not known(profile.get("identity", {}).get("name")) or not evidence(profile, "identity.name"):
        missing.append("identity.name")
    if not local_file_exists(profile, "career_document", base_dir):
        missing.append("career_document.path")
    if not valid_contact(profile):
        missing.append("contact")
    elif not contact_has_evidence(profile):
        missing.append("contact.evidence")

    for field in ["target_roles", "preferred_locations", "available_from"]:
        key = f"intent.{field}"
        if not known(intent.get(field)) or not evidence(profile, key):
            missing.append(key)
    for key, allowed in ENUMS.items():
        field = key.split(".", 1)[1]
        if intent.get(field) not in allowed or not evidence(profile, key):
            missing.append(key)

    for field in ["education", "core_experiences"]:
        section = profile.get(field, {})
        if section.get("status") != "known" or not evidence(profile, field):
            missing.append(field)

    consultation = profile.get("career_consultation", {})
    for dimension in CONSULTATION_DIMENSIONS:
        if not completed_consultation_dimension(consultation.get(dimension)):
            missing.append(f"career_consultation.{dimension}")

    consent = profile.get("consent", {})
    ingest_missing = []
    if "resume.path" in missing:
        ingest_missing.append("resume.path")
    if "contact" in missing or "contact.evidence" in missing:
        ingest_missing.append("contact")
    if consent.get("confirmed") is not True:
        ingest_missing.append("consent.confirmed")
    else:
        for field in ["confirmed_at", "material_version", "idempotency_key"]:
            if not known(consent.get(field)):
                ingest_missing.append(f"consent.{field}")

    return {
        "profile_status": "可匹配" if not missing else "待补充",
        "missing_for_matching": missing,
        "next_questions": [QUESTIONS[missing[0]]] if missing else [],
        "ingest_ready": not ingest_missing,
        "missing_for_ingest": ingest_missing,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        resume = Path(directory) / "resume.pdf"
        resume.write_bytes(b"%PDF-test")
        career_document = Path(directory) / "职业经历.md"
        career_document.write_text("# 职业经历\n", encoding="utf-8")
        complete = {
            "schema_version": "fanhan-career-profile-v1",
            "resume": {"path": str(resume)},
            "identity": {"name": "张三"},
            "career_document": {"path": str(career_document)},
            "contact": {"email": "candidate@example.com", "phone_or_wechat": "unknown"},
            "intent": {
                "target_roles": ["AI 产品经理"],
                "employment_type": "full_time",
                "preferred_locations": ["上海"],
                "remote_preference": "conditional",
                "relocation_preference": "reject",
                "available_from": "2026-09-01",
            },
            "education": {"status": "known", "items": []},
            "core_experiences": {"status": "known", "items": []},
            "career_consultation": {
                dimension: {
                    "summary": f"已确认的{dimension}",
                    "confirmed": True,
                    "evidence": ["候选人明确回答"],
                }
                for dimension in CONSULTATION_DIMENSIONS
            },
            "evidence": {
                "identity.name": ["简历第 1 页"],
                "contact.email": ["简历第 1 页"],
                "intent.target_roles": ["候选人明确回答"],
                "intent.employment_type": ["候选人明确回答"],
                "intent.preferred_locations": ["候选人明确回答"],
                "intent.remote_preference": ["候选人明确回答"],
                "intent.relocation_preference": ["候选人明确回答"],
                "intent.available_from": ["候选人明确回答"],
                "education": ["简历教育经历"],
                "core_experiences": ["简历项目经历"],
            },
            "consent": {
                "confirmed": True,
                "confirmed_at": "2026-08-17T00:00:00Z",
                "material_version": "sha256:test",
                "idempotency_key": "test-application",
            },
        }
        result = evaluate(complete, Path(directory))
        assert result["profile_status"] == "可匹配"
        assert result["ingest_ready"] is True

        minimum = json.loads(json.dumps(complete, ensure_ascii=False))
        minimum["intent"] = {
            "target_roles": [], "employment_type": "unknown", "preferred_locations": [],
            "remote_preference": "unknown", "relocation_preference": "unknown",
            "available_from": "unknown",
        }
        minimum["education"] = {"status": "unknown", "items": []}
        minimum["core_experiences"] = {"status": "unknown", "items": []}
        result = evaluate(minimum, Path(directory))
        assert result["profile_status"] == "待补充"
        assert result["ingest_ready"] is True

        incomplete = json.loads(json.dumps(complete, ensure_ascii=False))
        incomplete["intent"]["preferred_locations"] = []
        incomplete["consent"] = {"confirmed": False}
        result = evaluate(incomplete, Path(directory))
        assert result["profile_status"] == "待补充"
        assert "intent.preferred_locations" in result["missing_for_matching"]
        assert result["missing_for_ingest"] == ["consent.confirmed"]

        no_consultation = json.loads(json.dumps(complete, ensure_ascii=False))
        no_consultation.pop("career_consultation")
        result = evaluate(no_consultation, Path(directory))
        assert result["profile_status"] == "待补充"
        assert result["missing_for_matching"][-5:] == [
            f"career_consultation.{dimension}" for dimension in CONSULTATION_DIMENSIONS
        ]
        assert len(result["next_questions"]) == 1
    print("profile_status self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", help="职业档案 JSON 路径")
    parser.add_argument("--output", help="可选的状态 JSON 输出路径")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.profile:
        parser.error("请提供职业档案 JSON 路径")
    path = Path(args.profile).expanduser().resolve()
    profile = json.loads(path.read_text(encoding="utf-8"))
    result = evaluate(profile, path.parent)
    result.update(schema_version="fanhan-profile-status-v1", profile_sha256=sha256(path))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        if ".fanhan-job-agent" not in output.parts:
            raise ValueError("状态文件必须写入 .fanhan-job-agent/")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
