"""Regressions for official-site fallback, pagination and runtime failures."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import browser_jobs
import career_cache
import career_sources
import external_jobs


class BrowserSourcesTest(unittest.TestCase):
    def test_main_and_hash_pagination_preserve_filters(self):
        self.assertEqual(browser_jobs.next_list_url("https://example.com/jobs?page=1&city=beijing"),
                         "https://example.com/jobs?page=2&city=beijing")
        self.assertEqual(browser_jobs.next_list_url("https://app.mokahr.com/apply/co/1#/jobs?page=1&city=beijing"),
                         "https://app.mokahr.com/apply/co/1#/jobs?page=2&city=beijing")
        self.assertEqual(browser_jobs.next_list_url("https://example.com/jobs"), "")

    def test_animated_join_link_can_follow_observed_moka_destination(self):
        url = "https://app.mokahr.com/apply/moonshot/148506#/jobs?page=1"
        links = browser_jobs.career_links([{"text": "加\n加\n入\n入\n我\n我\n们\n们", "href": url}],
                                         "https://careers.kimi.com/")
        self.assertEqual(links, [url])

    def test_actual_titles_need_not_contain_engineer_or_manager(self):
        jobs = browser_jobs.jobs_from_anchors([
            {"text": "急\nAI Search Builder\n发布于 2026-11-20\n北京市", "href": "#/job/search-1"},
            {"text": "Agent Harness 团队\n北京市 杭州市", "href": "#/job/harness-2"},
            {"text": "立即投递", "href": "#/job/apply-3"},
        ], "Kimi", "https://app.mokahr.com/apply/moonshot/1#/jobs", 10)
        self.assertEqual([job["title"] for job in jobs], ["AI Search Builder", "Agent Harness 团队"])
        self.assertEqual(jobs[0]["location"], "北京市")
        self.assertTrue(jobs[1]["job_url"].endswith("#/job/harness-2"))

    def test_distinct_hash_jobs_survive_deduplication(self):
        jobs = [career_sources.job_record("Kimi", "产品经理", "北京", f"https://app.mokahr.com/apply/co/1#/job/{n}")
                for n in range(2)]
        self.assertEqual(career_sources.select_jobs(jobs, "", 10)[1], 2)

    def test_query_is_applied_after_scanning_more_than_first_page(self):
        jobs = [career_sources.job_record("Kimi", "算法工程师", "北京", f"https://example.com/jobs/{n}")
                for n in range(30)]
        jobs.append(career_sources.job_record("Kimi", "产品经理", "北京", "https://example.com/jobs/31"))
        with patch.object(browser_jobs, "browse_official", return_value=jobs) as browse:
            result = career_sources.read_browser_source({"name": "Kimi", "url": "https://careers.kimi.com/"}, "产品经理", 1)
        self.assertEqual(result["jobs"][0]["title"], "产品经理")
        self.assertGreater(browse.call_args.args[2], 30)

    def test_successful_http_read_with_no_matches_does_not_open_browser(self):
        fetched = lambda url: (url, '<a href="/jobs/1">算法工程师</a>')
        with patch.object(browser_jobs, "browse_official") as browse:
            result = career_sources.read_official({"name": "公司", "url": "https://example.com/careers"}, "产品经理", 10, fetched)
        self.assertEqual(result["source_status"], "searched")
        self.assertEqual(result["jobs"], [])
        browse.assert_not_called()

    def test_missing_browser_dependency_is_reported(self):
        with patch.object(browser_jobs, "browse_official", side_effect=RuntimeError("browser_dependency_missing: install playwright")):
            result = career_sources.read_official({"name": "公司", "url": "https://example.com/"}, "", 10,
                                                 lambda url: (url, '<div id="root"></div>'))
        self.assertEqual(result["source_status"], "unavailable")
        self.assertIn("browser_dependency_missing", result["error"])

    def test_paid_sources_do_not_invoke_browser(self):
        with patch.object(browser_jobs, "browse_official") as browse:
            result = career_sources.read_browser_source({"name": "JobRadar", "url": "https://jobradar.cc/zh", "access": "会员主导"}, "", 10)
        self.assertEqual(result["jobs"], [])
        browse.assert_not_called()

    def test_default_search_caps_fallback_and_keeps_platform_results(self):
        records = [{"name": f"AI公司{n}", "url": f"https://official{n}.example/", "type": "公司招聘官网",
                    "access": "免费公开", "quality": "高"} for n in range(8)]
        records.append({"name": "JobRadar", "url": "https://jobradar.cc/zh", "type": "公司招聘官网", "access": "会员主导"})
        def rendered(record, query, limit):
            return {"source": record["name"], "source_url": record["url"], "source_status": "searched", "matched_jobs": 1,
                    "jobs": [career_sources.job_record(record["name"], "AI 产品经理", "北京", record["url"] + "jobs/1")]}
        watcha = {"source": "Watcha", "source_url": "https://watcha.cn/study/jobs", "source_status": "searched", "matched_jobs": 1,
                  "jobs": [career_sources.job_record("平台公司", "AI 产品经理", "北京", "https://watcha.cn/jobs/1")]}
        with patch.object(career_sources, "read_browser_source", side_effect=rendered) as render, \
             patch.object(external_jobs.watcha_jobs, "fetch_payload", return_value={}), \
             patch.object(external_jobs.watcha_jobs, "normalize", return_value=watcha):
            cache_file = Path("/tmp/career-cache-unit.json")
            cache_file.unlink(missing_ok=True)
            result = external_jobs.search_all("AI", 20, catalog={"records": records},
                                              fetch=lambda url: (url, '<div id="root"></div>'), browser_limit=2,
                                              cache_file=cache_file)
        self.assertEqual(render.call_count, 2)
        self.assertEqual(result["source_summary"]["browser_attempted"], 2)
        self.assertEqual(len(result["jobs"]), 3)
        self.assertIn("Watcha", {job["source"] for job in result["jobs"]})
        self.assertNotIn("JobRadar", result["sources_attempted"])

    def test_browser_is_closed_if_page_creation_fails(self):
        context = MagicMock()
        chromium = context.__enter__.return_value.chromium
        browser = MagicMock()
        browser.new_page.side_effect = RuntimeError("page failed")
        chromium.launch.side_effect = [RuntimeError("bundled browser missing"), browser]
        module = types.ModuleType("playwright.sync_api")
        module.sync_playwright = lambda: context
        with patch.dict(sys.modules, {"playwright": types.ModuleType("playwright"), "playwright.sync_api": module}):
            with self.assertRaisesRegex(RuntimeError, "page failed"):
                browser_jobs.browse_official("https://example.com/", "公司")
        browser.close.assert_called_once()

    def test_browser_slots_prefer_named_company_then_oldest_check(self):
        moment = career_cache.now_utc()
        cache = {"entries": {
            "已查过": {"fetched_at": "2026-11-21T00:00:00+00:00", "jobs": [], "failure_reason": "parser_gap"},
            "刚查过": {"fetched_at": moment.isoformat(), "jobs": [], "failure_reason": "parser_gap"},
        }}
        records = [
            {"name": "刚查过", "url": "https://new.example"},
            {"name": "已查过", "url": "https://old.example"},
            {"name": "小米", "url": "https://hr.xiaomi.com/"},
            {"name": "从未检查", "url": "https://never.example"},
        ]
        picked = [item["name"] for item in career_cache.pick_browser_targets(records, cache, "小米产品", 3, moment)]
        self.assertEqual(picked, ["小米", "从未检查", "已查过"])

    def test_fresh_success_does_not_spend_a_browser_slot(self):
        moment = career_cache.now_utc()
        cache_file = Path("/tmp/career-cache-fresh.json")
        career_cache.save({"entries": {"DeepSeek 深度求索": {
            "fetched_at": moment.isoformat(),
            "jobs": [career_sources.job_record("DeepSeek", "服务端开发工程师", "北京", "https://example.com/job/1")],
            "collected_count": 1,
            "entry_url": "https://talent.deepseek.com/",
        }}}, cache_file)
        records = [{"name": "DeepSeek 深度求索", "url": "https://talent.deepseek.com/", "type": "公司招聘官网", "access": "免费公开", "quality": "高"}]
        watcha = {"source": "Watcha", "source_url": "https://watcha.cn/study/jobs", "source_status": "searched", "matched_jobs": 0, "jobs": []}
        with patch.object(career_sources, "read_browser_source") as render, \
             patch.object(external_jobs.watcha_jobs, "fetch_payload", return_value={}), \
             patch.object(external_jobs.watcha_jobs, "normalize", return_value=watcha):
            result = external_jobs.search_all("工程师", 5, catalog={"records": records},
                                              fetch=lambda url: (url, "<div id='root'></div>"), browser_limit=5,
                                              cache_file=cache_file)
        render.assert_not_called()
        self.assertEqual(result["jobs"][0]["title"], "服务端开发工程师")
        deepseek = next(item for item in result["sources"] if item["source"] == "DeepSeek 深度求索")
        self.assertEqual(deepseek["read_method"], "cache")
        self.assertGreater(deepseek["collected_count"], 0)

    def test_fresh_official_jobs_match_without_rereading_the_site(self):
        moment = career_cache.now_utc()
        cache_file = Path("/tmp/career-cache-match.json")
        career_cache.save({"entries": {
            "蚂蚁集团": {
                "fetched_at": moment.isoformat(),
                "entry_url": "https://talent.antgroup.com/off-campus-home",
                "jobs": [
                    career_sources.job_record("蚂蚁集团", "语言大模型语料优化", "杭州", "https://talent.antgroup.com/job/1"),
                    career_sources.job_record("蚂蚁集团", "客户经理", "杭州", "https://talent.antgroup.com/job/2"),
                ],
                "collected_count": 2,
            },
            "硅基流动 SiliconFlow": {
                "fetched_at": moment.isoformat(),
                "entry_url": "https://app.mokahr.com/social-recruitment/siliconflow/151750#/",
                "jobs": [career_sources.job_record(
                    "硅基流动 SiliconFlow", "大模型推理引擎架构师", "北京",
                    "https://app.mokahr.com/social-recruitment/siliconflow/151750#/job/architect",
                )],
                "collected_count": 1,
            },
        }}, cache_file)
        records = [
            {"name": "蚂蚁集团", "url": "https://talent.antgroup.com/off-campus-home", "type": "公司招聘官网", "access": "免费公开", "quality": "高"},
            {"name": "硅基流动 SiliconFlow", "url": "https://app.mokahr.com/social-recruitment/siliconflow/151750#/", "type": "公司招聘官网", "access": "免费公开", "quality": "高"},
        ]
        watcha = {"source": "Watcha", "source_url": "https://watcha.cn/study/jobs", "source_status": "searched", "matched_jobs": 0, "jobs": []}
        def fail_fetch(url):
            raise AssertionError(url)
        with patch.object(career_sources, "read_official", side_effect=AssertionError("should use cache")), \
             patch.object(career_sources, "read_browser_source", side_effect=AssertionError("should use cache")), \
             patch.object(external_jobs.watcha_jobs, "fetch_payload", return_value={}), \
             patch.object(external_jobs.watcha_jobs, "normalize", return_value=watcha):
            result = external_jobs.search_all("大模型", 20, catalog={"records": records},
                                              fetch=fail_fetch, browser_limit=0, cache_file=cache_file)
        titles = {job["title"] for job in result["jobs"]}
        self.assertIn("语言大模型语料优化", titles)
        self.assertIn("大模型推理引擎架构师", titles)
        self.assertNotIn("客户经理", titles)
        self.assertTrue(all(item["read_method"] == "cache" for item in result["sources"] if item["source"] in {"蚂蚁集团", "硅基流动 SiliconFlow"}))


if __name__ == "__main__":
    unittest.main()
