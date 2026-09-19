"""Unit tests for MarketRecommender and DashboardBuilder."""

import os
import csv
import json
import unittest
import tempfile
from src.recommender import MarketRecommender
from src.build_site import DashboardBuilder


class TestMarketRecommender(unittest.TestCase):

    def setUp(self):
        self.recommender = MarketRecommender()

    def test_profile_attributes(self):
        self.assertEqual(self.recommender.company_name, "NovaFactory AI")
        self.assertGreaterEqual(len(self.recommender.competitors), 3)
        self.assertGreaterEqual(len(self.recommender.interest_keywords), 5)

    def test_scoring_weights(self):
        # Competitor article
        art_comp = {
            "title": "InspectAI 신규 AI 검사 장비 출시",
            "content": "경쟁사 InspectAI가 제조 불량 검사 장비를 출시했다.",
            "category": "competitor",
            "date": "2026-09-18",
            "source_name": "산업뉴스",
            "company_tag": "InspectAI"
        }
        score_comp, sub_comp, reason_comp = self.recommender.score_article_rule_based(art_comp)
        self.assertGreaterEqual(score_comp, 50)
        self.assertIn("InspectAI", sub_comp["matched_competitors"])
        self.assertIn("경쟁사", reason_comp)

        # Funding article
        art_fund = {
            "title": "2026년 중소기업 스마트공장 AI 바우처 지원사업 공고",
            "content": "중소벤처기업부는 AI 바우처 보급사업을 시작한다.",
            "category": "funding",
            "date": "2026-09-18",
            "source_name": "정책뉴스",
            "company_tag": ""
        }
        score_fund, sub_fund, reason_fund = self.recommender.score_article_rule_based(art_fund)
        self.assertGreaterEqual(score_fund, 60)
        self.assertIn("정부지원", reason_fund)

    def test_pipeline_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_csv = os.path.join(tmp_dir, "recommended.csv")
            rec = MarketRecommender(output_path=out_csv, top_n=10)
            res = rec.run_recommendation()
            self.assertEqual(len(res), 10)
            self.assertTrue(os.path.exists(out_csv))
            with open(out_csv, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 10)
                self.assertIn("score", reader.fieldnames)
                self.assertIn("recommendation_reason", reader.fieldnames)
                self.assertIn("rank", reader.fieldnames)


class TestDashboardBuilder(unittest.TestCase):

    def test_site_building(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            builder = DashboardBuilder(output_dir=tmp_dir)
            builder.build()

            json_file = os.path.join(tmp_dir, "report.json")
            html_file = os.path.join(tmp_dir, "index.html")

            self.assertTrue(os.path.exists(json_file))
            self.assertTrue(os.path.exists(html_file))

            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.assertIn("metadata", data)
                self.assertIn("top_10", data)
                self.assertLessEqual(len(data["top_10"]), 10)

            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("NovaFactory AI", content)
                self.assertIn("TOP 10", content)


if __name__ == "__main__":
    unittest.main()
