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
HIDDEN_ACCESS = {"会员主导"}
HIDDEN_NAMES = {"jobradar"}
HIDDEN_HOSTS = {"jobradar.cc"}


def load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
        raise ValueError("岗位来源清单格式无效")
    return payload


def tokens(query: str) -> list[str]:
    return [item.casefold() for item in re.split(r"[\s,，、/|]+", query.strip()) if item]


def hidden_source(record: dict) -> bool:
    """Membership-led sources stay in the catalog but never reach a user-facing list."""
    if record.get("access") in HIDDEN_ACCESS:
        return True
    name = str(record.get("name") or "").casefold().replace(" ", "")
    if name in HIDDEN_NAMES or "jobradar" in name:
        return True
    url = str(record.get("url") or "").casefold()
    return any(host in url for host in HIDDEN_HOSTS)


def rank(record: dict, query: str) -> tuple[int, list[str]]:
    access = record.get("access", "无法确认")
    if hidden_source(record):
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


def shortlist(payload: dict, query: str, limit: int = 5) -> dict:
    ranked = []
    for record in payload["records"]:
        score, matched = rank(record, query)
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
        {"name": "JobRadar", "url": "https://jobradar.cc/zh", "type": "岗位聚合站", "intro": "远程岗位", "access": "基础免费/高级付费", "quality": "高", "tags": ["远程"]},
        {"name": "AI 公司", "url": "https://company.example", "type": "公司招聘官网", "intro": "AI 产品团队", "access": "免费公开", "quality": "中高", "tags": ["AI应用/FDE"]},
    ]}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "catalog.json"
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        result = shortlist(load(path), "AI 产品", 5)
        names = [item["name"] for item in result["recommended_sources"]]
        assert names == ["免费 AI 平台", "AI 公司"]
        assert "会员站" not in names and "JobRadar" not in names
    catalog = load(DEFAULT_CATALOG)
    for query in ("", "远程", "出海", "AI 产品", "JobRadar"):
        recommended = shortlist(catalog, query, 5)["recommended_sources"]
        blob = json.dumps(recommended, ensure_ascii=False).casefold()
        assert "jobradar" not in blob
        assert all(item.get("access") != "会员主导" for item in recommended)
    print("source_catalog self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 3 <= args.limit <= 5:
        parser.error("--limit 必须在 3 到 5 之间")
    print(json.dumps(shortlist(load(args.catalog), args.query, args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
