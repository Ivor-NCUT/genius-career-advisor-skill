#!/usr/bin/env python3
"""Select a small, relevant set of job sources from the bundled catalog."""

import argparse
import json
import re
import tempfile
from pathlib import Path


DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "data" / "job-source-catalog.json"
QUALITY_SCORE = {"高": 40, "中高": 30, "中": 20, "波动较大": 0, "待核实": -10}
ACCESS_SCORE = {"免费公开": 20, "免费注册后使用": 15, "基础免费/高级付费": 5, "会员主导": -100, "无法确认": -20}


def load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
        raise ValueError("岗位来源清单格式无效")
    return payload


def tokens(query: str) -> list[str]:
    return [item.casefold() for item in re.split(r"[\s,，、/|]+", query.strip()) if item]


def rank(record: dict, query: str, include_paid: bool) -> tuple[int, list[str]]:
    access = record.get("access", "无法确认")
    if access == "会员主导" and not include_paid:
        return -10_000, []
    searchable = " ".join(str(record.get(key, "")) for key in (
        "name", "intro", "target_audience", "direction",
    )) + " " + " ".join(record.get("tags") or [])
    searchable = searchable.casefold()
    matched = [token for token in tokens(query) if token in searchable]
    score = QUALITY_SCORE.get(record.get("quality"), -10) + ACCESS_SCORE.get(access, -20)
    score += 18 * len(matched)
    if record.get("type") != "公司招聘官网":
        score += 5
    return score, matched


def shortlist(payload: dict, query: str, limit: int = 5, include_paid: bool = False) -> dict:
    ranked = []
    for record in payload["records"]:
        score, matched = rank(record, query, include_paid)
        if score <= -10_000:
            continue
        item = dict(record)
        item["score"] = score
        item["reason"] = "、".join(filter(None, [
            f"匹配：{'、'.join(matched)}" if matched else "通用高质量来源",
            item.get("quality", ""), item.get("access", ""),
        ]))
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], item["name"]))
    broad = [item for item in ranked if item.get("type") != "公司招聘官网"]
    direct = [item for item in ranked if item.get("type") == "公司招聘官网"]
    selected = broad[: min(3, limit)] + direct[: max(0, limit - min(3, limit))]
    if len(selected) < limit:
        used = {item["url"] for item in selected}
        selected.extend(item for item in ranked if item["url"] not in used)
    return {
        "query": query,
        "catalog_generated_at": payload.get("generated_at"),
        "catalog_count": len(payload["records"]),
        "recommended_sources": selected[:limit],
        "requires_user_confirmation": True,
    }


def self_test() -> None:
    fixture = {"schema_version": 1, "generated_at": "2026-08-20", "records": [
        {"name": "免费 AI 平台", "url": "https://free.example", "type": "招聘平台", "intro": "AI 产品岗位", "access": "免费公开", "quality": "高", "tags": ["AI/大模型", "产品/设计/运营"]},
        {"name": "会员站", "url": "https://paid.example", "type": "岗位聚合站", "intro": "AI 产品岗位", "access": "会员主导", "quality": "高", "tags": ["AI/大模型"]},
        {"name": "AI 公司", "url": "https://company.example", "type": "公司招聘官网", "intro": "AI 产品团队", "access": "免费公开", "quality": "中高", "tags": ["AI应用/FDE"]},
    ]}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "catalog.json"
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        result = shortlist(load(path), "AI 产品", 2)
        assert [item["name"] for item in result["recommended_sources"]] == ["免费 AI 平台", "AI 公司"]
        assert all(item["name"] != "会员站" for item in result["recommended_sources"])
    print("source_catalog self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--include-paid", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 3 <= args.limit <= 5:
        parser.error("--limit 必须在 3 到 5 之间")
    print(json.dumps(shortlist(load(args.catalog), args.query, args.limit, args.include_paid), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
