#!/usr/bin/env python3
"""Choose an internal search set from the bundled catalog.

The shortlist is for the skill to search immediately. It is not a user-facing
source recommendation and must not be shown as a confirmation step.
"""

import argparse
import json
import re
import tempfile
from pathlib import Path


DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "data" / "job-source-catalog.json"
SKILL_ROOT = DEFAULT_CATALOG.parent.parent
REPO_ROOT = SKILL_ROOT.parent
QUALITY_SCORE = {"高": 40, "中高": 30, "中": 20, "波动较大": 0, "待核实": -10}
ACCESS_SCORE = {"免费公开": 20, "免费注册后使用": 15, "基础免费/高级付费": 5, "会员主导": -100, "无法确认": -20}
OFFICIAL_TYPE = "公司招聘官网"
# 当前快照大约几十家官网，会全部检索。快照增长到一百家以上时，按查询重合只取前 N 家，避免一次搜索被慢站点拖死。
OFFICIAL_SITE_CAP = 80
SEARCH_SCOPE = "public_platforms_and_official_career_sites"


def load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
        raise ValueError("岗位来源清单格式无效")
    return payload


def tokens(query: str) -> list[str]:
    return [item.casefold() for item in re.split(r"[\s,，、/|]+", query.strip()) if item]


def hidden_from_search(record: dict) -> bool:
    """Membership-led boards stay out of search even if someone passes --include-paid."""
    name = str(record.get("name", ""))
    folded = name.casefold().replace(" ", "")
    url = str(record.get("url", "")).casefold()
    if "jobradar" in folded or "jobradar" in url:
        return True
    if "出海聘" in name or "chuhaipin" in url:
        return True
    return False


def rank(record: dict, query: str, include_paid: bool) -> tuple[int, list[str]]:
    access = record.get("access", "无法确认")
    if hidden_from_search(record) or (access == "会员主导" and not include_paid):
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


def match_score(record: dict, query: str) -> int:
    access = record.get("access", "无法确认")
    searchable = " ".join(str(record.get(key, "")) for key in (
        "name", "intro", "target_audience", "direction",
    )) + " " + " ".join(record.get("tags") or [])
    matched = [token for token in tokens(query) if token in searchable.casefold()]
    score = QUALITY_SCORE.get(record.get("quality"), -10) + ACCESS_SCORE.get(access, -20)
    return score + 18 * len(matched)


def search_plan(payload: dict, query: str = "", include_paid: bool = False, official_cap: int = OFFICIAL_SITE_CAP) -> dict:
    """Records the default search actually fetches.

    Public platforms and official career sites are both included. The small
    `shortlist()` sample is not this set. Membership-led sources are omitted.
    """
    public = []
    official = []
    for record in payload["records"]:
        if hidden_from_search(record):
            continue
        if record.get("access") == "会员主导" and not include_paid:
            continue
        if not str(record.get("url") or "").startswith(("http://", "https://")):
            continue
        if record.get("type") == OFFICIAL_TYPE:
            official.append(record)
        else:
            public.append(record)
    official.sort(key=lambda record: (-match_score(record, query), str(record.get("name", ""))))
    selected = official[: max(0, official_cap)]
    return {
        "query": query,
        "catalog_generated_at": payload.get("generated_at"),
        "catalog_count": len(payload["records"]),
        "internal_only": True,
        "requires_user_confirmation": False,
        "search_immediately": True,
        "search_scope": SEARCH_SCOPE,
        "official_sites_are_searched": True,
        "official_site_cap": official_cap,
        "official_sites_total": len(official),
        "official_sites_selected": len(selected),
        "public_platforms": public,
        "official_sites": selected,
        "also_search": ["Watcha"],
        "cap_note": (
            f"公司招聘官网不足 {official_cap} 家时全部检索；"
            f"超过时按查询与名称、简介、标签的重合取前 {official_cap} 家。"
        ),
    }


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
        "internal_only": True,
        "requires_user_confirmation": False,
        "search_immediately": True,
        "search_scope": SEARCH_SCOPE,
        "official_sites_are_searched": True,
        "recommended_sources_are_not_the_search_boundary": True,
        "live_job_lists": ["public_platforms", "official_career_sites", "Watcha"],
        "recommended_sources": selected[:limit],
    }


def assert_default_path_copy() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    contract = (SKILL_ROOT / "references" / "v1-contract.md").read_text(encoding="utf-8")
    checklist = (SKILL_ROOT / "references" / "test-record-template.md").read_text(encoding="utf-8")
    prompt = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / "docs" / "assets" / "readme" / "workflow.svg").read_text(encoding="utf-8")
    combined = "\n".join((skill, readme, contract, checklist, prompt, workflow))
    for phrase in (
        "按这组",
        "你确认后再搜索",
        "我确认后再搜索",
        "推荐 3–5",
        "推荐 3-5",
        "先用短表展示",
        "用户可以增删来源",
        "没有明确同意前不得依次打开网站",
        "从我确认的外部渠道",
        "选择来源",
    ):
        assert phrase not in combined, phrase
    assert "不要展示来源" in skill
    assert "直接搜索" in skill
    assert "requires_user_confirmation" in skill
    assert "false" in skill
    assert "公司招聘官网" in skill
    assert "并行" in skill
    for banned in ("只把 Bonjour 和 Watcha", "只有 Bonjour 和 Watcha", "采用 Bonjour 与 Watcha 的实时岗位"):
        assert banned not in skill, banned
    assert "公司官网" in readme or "招聘官网" in readme
    for surface in (readme, prompt, workflow):
        assert "JobRadar" not in surface


def self_test() -> None:
    fixture = {"schema_version": 1, "generated_at": "2026-08-20", "records": [
        {"name": "免费 AI 平台", "url": "https://free.example", "type": "招聘平台", "intro": "AI 产品岗位", "access": "免费公开", "quality": "高", "tags": ["AI/大模型", "产品/设计/运营"]},
        {"name": "会员站", "url": "https://paid.example", "type": "岗位聚合站", "intro": "AI 产品岗位", "access": "会员主导", "quality": "高", "tags": ["AI/大模型"]},
        {"name": "JobRadar", "url": "https://jobradar.cc/zh", "type": "岗位聚合站", "intro": "AI 产品岗位", "access": "基础免费/高级付费", "quality": "高", "tags": ["AI/大模型", "远程"]},
        {"name": "出海聘", "url": "https://www.chuhaipin.cn/", "type": "岗位聚合站", "intro": "AI 产品岗位", "access": "会员主导", "quality": "高", "tags": ["海外/出海"]},
        {"name": "AI 公司", "url": "https://company.example", "type": "公司招聘官网", "intro": "AI 产品团队", "access": "免费公开", "quality": "中高", "tags": ["AI应用/FDE"]},
    ]}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "catalog.json"
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        result = shortlist(load(path), "AI 产品", 2)
        assert [item["name"] for item in result["recommended_sources"]] == ["免费 AI 平台", "AI 公司"]
        assert result["requires_user_confirmation"] is False
        assert result["search_immediately"] is True
        assert result["internal_only"] is True
        assert result["live_job_lists"] == ["public_platforms", "official_career_sites", "Watcha"]
        assert result["official_sites_are_searched"] is True
        assert result["recommended_sources_are_not_the_search_boundary"] is True
        paid = shortlist(load(path), "AI 产品", 5, include_paid=True)
        paid_names = [item["name"] for item in paid["recommended_sources"]]
        assert "JobRadar" not in paid_names
        assert "出海聘" not in paid_names
        plan = search_plan(load(path), "AI 产品")
        assert [item["name"] for item in plan["public_platforms"]] == ["免费 AI 平台"]
        assert [item["name"] for item in plan["official_sites"]] == ["AI 公司"]
        assert plan["also_search"] == ["Watcha"]
        assert plan["requires_user_confirmation"] is False
    many = {"schema_version": 1, "generated_at": "2026-08-20", "records": [
        {"name": f"公司{index:03d}", "url": f"https://co{index}.example/jobs", "type": "公司招聘官网", "intro": "通用岗位", "access": "免费公开", "quality": "中", "tags": []}
        for index in range(90)
    ] + [
        {"name": "AI 产品公司", "url": "https://ai-product.example/jobs", "type": "公司招聘官网", "intro": "AI 产品团队", "access": "免费公开", "quality": "中", "tags": ["产品/设计/运营"]},
        {"name": "JobRadar", "url": "https://jobradar.cc/zh", "type": "岗位聚合站", "intro": "AI 产品", "access": "基础免费/高级付费", "quality": "高", "tags": []},
    ]}
    capped = search_plan(many, "AI 产品", official_cap=80)
    assert capped["official_sites_total"] == 91
    assert capped["official_sites_selected"] == 80
    assert capped["official_sites"][0]["name"] == "AI 产品公司"
    assert all(item["name"] != "JobRadar" for item in capped["public_platforms"])
    bundled = shortlist(load(DEFAULT_CATALOG), "AI 产品 远程", 5)
    names = [item["name"] for item in bundled["recommended_sources"]]
    assert bundled["requires_user_confirmation"] is False
    assert bundled["search_immediately"] is True
    assert "JobRadar" not in names
    assert all("出海聘" not in item["name"] for item in bundled["recommended_sources"])
    assert all(item.get("access") != "会员主导" for item in bundled["recommended_sources"])
    bundled_plan = search_plan(load(DEFAULT_CATALOG), "AI 产品 远程")
    platform_names = [item["name"] for item in bundled_plan["public_platforms"]]
    assert bundled_plan["requires_user_confirmation"] is False
    assert bundled_plan["official_sites_are_searched"] is True
    assert bundled_plan["official_sites_total"] == bundled_plan["official_sites_selected"]
    assert bundled_plan["official_sites_selected"] > 5
    assert "JobRadar" not in platform_names
    assert all("出海聘" not in name for name in platform_names)
    assert any("找工地图" in name for name in platform_names)
    assert any("V2EX" in name for name in platform_names)
    assert any("HiringCafe" in name for name in platform_names)
    assert all(item.get("access") != "会员主导" for item in bundled_plan["public_platforms"])
    assert all(item.get("type") == "公司招聘官网" for item in bundled_plan["official_sites"])
    official_by_name = {item["name"]: item["url"] for item in bundled_plan["official_sites"]}
    for name in ("优必选 UBTECH", "帕西尼感知 PaXini", "思必驰 AISpeech", "摩尔线程", "普渡科技 Pudu", "曦智科技 Lightelligence", "梅卡曼德 Mech-Mind"):
        assert name in official_by_name, name
        assert "zhiye.com" in official_by_name[name]
    assert official_by_name["爱诗科技 PixVerse"] == "https://aisphere.jobs.feishu.cn/join"
    assert official_by_name["面壁智能 ModelBest"] == "https://modelbest.jobs.feishu.cn/career"
    assert official_by_name["百川智能"] == "https://careers.baichuan-inc.com/"
    assert "mokahr.com" in official_by_name["银河通用 Galbot"]
    assert_default_path_copy()
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
