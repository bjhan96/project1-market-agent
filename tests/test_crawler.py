"""Unit and integration tests for MarketCrawler using unittest."""

import os
import csv
import unittest
import tempfile
from src.crawler import MarketCrawler


class TestMarketCrawler(unittest.TestCase):

    def test_profile_loading(self):
        crawler = MarketCrawler()
        self.assertIsNotNone(crawler.profile)
        self.assertIn("NovaFactory AI", crawler.profile.get("company_name", ""))
        self.assertGreaterEqual(len(crawler.competitors), 3)
        self.assertGreaterEqual(len(crawler.interest_keywords), 5)

    def test_article_classification(self):
        crawler = MarketCrawler()
        
        # Competitor check
        cat, comp_tag, kws = crawler._classify_article("VisionForge 신제품 발표", "비전 기반 AI 검사 솔루션 출시")
        self.assertEqual(cat, "competitor")
        self.assertEqual(comp_tag, "VisionForge")
        
        # Funding check
        cat, comp_tag, kws = crawler._classify_article("2026 중소기업 AI 바우처 사업 공고", "지원사업 접수 안내")
        self.assertEqual(cat, "funding")
        
        # Technology check
        cat, comp_tag, kws = crawler._classify_article("머신비전 딥러닝 결함 탐지 알고리즘", "엣지 AI 검사 성능 고도화")
        self.assertEqual(cat, "technology")

    def test_fault_tolerance_on_failed_source(self):
        crawler = MarketCrawler()
        # Try fetching from an invalid URL
        count = crawler._fetch_rss("Invalid Test Source", "https://invalid-non-existent-domain-12345.com/rss")
        self.assertEqual(count, 0)
        self.assertTrue(any(s[0] == "Invalid Test Source" for s in crawler.failed_sources))

    def test_fallback_merging_when_under_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_file = os.path.join(tmp_dir, "test_merged.csv")
            crawler = MarketCrawler(
                output_path=output_file,
                target_count=500  # set target higher to trigger fallback merge test
            )
            # Mock some live articles
            for i in range(50):
                crawler._add_article(
                    title=f"Live Article {i}",
                    link=f"https://example.com/live/{i}",
                    pub_date="2026-09-19",
                    content="테스트 본문",
                    source_name="Test Source",
                    category="market"
                )
            self.assertEqual(len(crawler.crawled_articles), 50)
            
            # Merge fallback
            added = crawler._merge_fallback()
            self.assertGreater(added, 0)
            self.assertGreaterEqual(len(crawler.crawled_articles), 500)
            
            # Save and check CSV
            crawler._save_to_csv()
            self.assertTrue(os.path.exists(output_file))
            
            with open(output_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                origins = set(r["data_origin"] for r in rows)
                self.assertIn("live_crawler", origins)
                self.assertIn("synthetic_fallback", origins)


if __name__ == "__main__":
    unittest.main()
