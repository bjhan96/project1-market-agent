"""Unit and integration tests for MarketPipeline."""

import os
import unittest
from unittest.mock import patch, MagicMock
from src.run_pipeline import MarketPipeline


class TestMarketPipeline(unittest.TestCase):

    def test_pipeline_initialization(self):
        pipeline = MarketPipeline()
        self.assertIsNotNone(pipeline.config_path)
        self.assertIsNotNone(pipeline.raw_csv)
        self.assertIsNotNone(pipeline.cleaned_csv)
        self.assertIsNotNone(pipeline.recommended_csv)
        self.assertEqual(pipeline.target_count, 200)

    def test_pipeline_recording(self):
        pipeline = MarketPipeline()
        pipeline.record_stage("TEST_STAGE", "SUCCESS", "Test passed", 0.05)
        self.assertIn("TEST_STAGE", pipeline.stages)
        self.assertEqual(pipeline.stages["TEST_STAGE"]["status"], "SUCCESS")
        self.assertEqual(pipeline.stages["TEST_STAGE"]["details"], "Test passed")

    @patch("src.run_pipeline.MarketCrawler")
    def test_pipeline_warning_on_fallback(self, mock_crawler_cls):
        # Mock crawler returning fallback usage
        mock_instance = MagicMock()
        mock_instance.crawl.return_value = {
            "total_count": 250,
            "live_count": 150,
            "fallback_count": 100,
            "failed_sources": [("Failed RSS", "403 Forbidden")]
        }
        mock_crawler_cls.return_value = mock_instance

        pipeline = MarketPipeline()
        ok = pipeline.run_stage_crawler()
        self.assertTrue(ok)
        self.assertEqual(pipeline.stages["1. CRAWLER"]["status"], "WARNING")
        self.assertIn("Fallback: 100", pipeline.stages["1. CRAWLER"]["details"])

    @patch("src.run_pipeline.MarketCrawler")
    @patch("src.run_pipeline.MarketDataCleaner")
    @patch("src.run_pipeline.MarketRecommender")
    @patch("src.run_pipeline.DashboardBuilder")
    def test_pipeline_full_run_mocked(self, mock_builder_cls, mock_recom_cls, mock_clean_cls, mock_crawl_cls):
        # Mock each stage
        mock_crawl_cls.return_value.crawl.return_value = {
            "total_count": 300,
            "live_count": 300,
            "fallback_count": 0,
            "failed_sources": []
        }
        mock_clean_cls.return_value.clean_dataset.return_value = {
            "raw_count": 300,
            "final_count": 300,
            "total_duplicates_removed": 0,
            "total_missing_invalid_removed": 0
        }
        mock_recom_cls.return_value.run_recommendation.return_value = [{"title": f"T{i}", "score": 80} for i in range(30)]
        mock_recom_cls.return_value.use_llm = False

        # Set fake existing files
        pipeline = MarketPipeline()
        with patch("os.path.exists", return_value=True), patch("os.path.getsize", return_value=12345):
            success = pipeline.run()
            self.assertTrue(success)
            self.assertEqual(pipeline.stages["1. CRAWLER"]["status"], "SUCCESS")
            self.assertEqual(pipeline.stages["2. CLEANER"]["status"], "SUCCESS")
            self.assertEqual(pipeline.stages["3. RECOMMENDER"]["status"], "SUCCESS")
            self.assertEqual(pipeline.stages["4. DASHBOARD"]["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
