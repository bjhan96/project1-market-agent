"""Unit and integration tests for MarketDataCleaner."""

import os
import csv
import unittest
import tempfile
from src.cleaner import MarketDataCleaner


class TestMarketDataCleaner(unittest.TestCase):

    def setUp(self):
        self.cleaner = MarketDataCleaner()

    def test_clean_text_html_and_entities(self):
        raw = "<p>제조 <b>AX</b> 혁신 &nbsp;&nbsp; 가이드라인 &amp; 표준</p>"
        cleaned = self.cleaner.clean_text(raw)
        self.assertEqual(cleaned, "제조 AX 혁신 가이드라인 & 표준")

    def test_normalize_date(self):
        # RFC 2822
        d1 = self.cleaner.normalize_date("Sat, 19 Sep 2026 00:15:55 GMT")
        self.assertEqual(d1, "2026-09-19")
        
        # YYYY.MM.DD
        d2 = self.cleaner.normalize_date("2026.08.15")
        self.assertEqual(d2, "2026-08-15")

        # YYYY/MM/DD
        d3 = self.cleaner.normalize_date("2026/03/05")
        self.assertEqual(d3, "2026-03-05")

        # ISO format
        d4 = self.cleaner.normalize_date("2026-07-24T12:30:00Z")
        self.assertEqual(d4, "2026-07-24")

    def test_is_valid_title(self):
        # Valid title
        self.assertTrue(self.cleaner.is_valid_title("스마트팩토리 AI 검사 솔루션 도입"))
        self.assertTrue(self.cleaner.is_valid_title("InspectAI 신규 라인업"))

        # Too short
        self.assertFalse(self.cleaner.is_valid_title("AI"))
        self.assertFalse(self.cleaner.is_valid_title("   "))
        self.assertFalse(self.cleaner.is_valid_title(""))
        self.assertFalse(self.cleaner.is_valid_title(None))

        # Only symbols
        self.assertFalse(self.cleaner.is_valid_title("---***---"))

    def test_deduplication_and_filtering_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_csv = os.path.join(tmp_dir, "raw_dirty.csv")
            output_csv = os.path.join(tmp_dir, "processed_clean.csv")

            dirty_data = [
                # 1. Normal valid row
                {
                    "article_id": "TEST-0001",
                    "category": "market",
                    "title": "정상 기사 제목 1",
                    "date": "2026-09-19",
                    "content": "정상 본문 1 &nbsp;",
                    "summary": "정상 요약 1",
                    "source_url": "https://example.com/1",
                    "source_name": "테스트뉴스",
                    "company_tag": "",
                    "keywords": "AI",
                    "collected_at": "2026-09-19T10:00:00",
                    "has_null": "false",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawler"
                },
                # 2. Exact duplicate of row 1
                {
                    "article_id": "TEST-0001",
                    "category": "market",
                    "title": "정상 기사 제목 1",
                    "date": "2026-09-19",
                    "content": "정상 본문 1 &nbsp;",
                    "summary": "정상 요약 1",
                    "source_url": "https://example.com/1",
                    "source_name": "테스트뉴스",
                    "company_tag": "",
                    "keywords": "AI",
                    "collected_at": "2026-09-19T10:00:00",
                    "has_null": "false",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawler"
                },
                # 3. URL duplicate
                {
                    "article_id": "TEST-0002",
                    "category": "market",
                    "title": "다른 제목이지만 같은 URL",
                    "date": "2026-09-19",
                    "content": "본문",
                    "summary": "요약",
                    "source_url": "https://example.com/1",
                    "source_name": "테스트뉴스",
                    "company_tag": "",
                    "keywords": "AI",
                    "collected_at": "2026-09-19T10:00:00",
                    "has_null": "false",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawler"
                },
                # 4. Title duplicate (whitespace/punctuation variant)
                {
                    "article_id": "TEST-0003",
                    "category": "market",
                    "title": "정상  기사  제목  1!!",
                    "date": "2026-09-19",
                    "content": "본문",
                    "summary": "요약",
                    "source_url": "https://example.com/3",
                    "source_name": "테스트뉴스",
                    "company_tag": "",
                    "keywords": "AI",
                    "collected_at": "2026-09-19T10:00:00",
                    "has_null": "false",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawler"
                },
                # 5. Empty title
                {
                    "article_id": "TEST-0004",
                    "category": "market",
                    "title": "",
                    "date": "2026-09-19",
                    "content": "본문",
                    "summary": "요약",
                    "source_url": "https://example.com/4",
                    "source_name": "테스트뉴스",
                    "company_tag": "",
                    "keywords": "AI",
                    "collected_at": "2026-09-19T10:00:00",
                    "has_null": "true",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawler"
                },
                # 6. Too short title
                {
                    "article_id": "TEST-0005",
                    "category": "market",
                    "title": "단어",
                    "date": "2026-09-19",
                    "content": "본문",
                    "summary": "요약",
                    "source_url": "https://example.com/5",
                    "source_name": "테스트뉴스",
                    "company_tag": "",
                    "keywords": "AI",
                    "collected_at": "2026-09-19T10:00:00",
                    "has_null": "false",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawler"
                },
                # 7. Another valid row
                {
                    "article_id": "TEST-0006",
                    "category": "technology",
                    "title": "새로운 머신비전 AI 품질검사 플랫폼",
                    "date": "2026.05.20",
                    "content": "<b>혁신 솔루션</b>",
                    "summary": "요약",
                    "source_url": "https://example.com/6",
                    "source_name": "테스트뉴스",
                    "company_tag": "",
                    "keywords": "머신비전",
                    "collected_at": "2026-09-19T10:00:00",
                    "has_null": "false",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawler"
                }
            ]

            fieldnames = list(dirty_data[0].keys())
            with open(input_csv, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for d in dirty_data:
                    writer.writerow(d)

            cleaner = MarketDataCleaner(input_path=input_csv, output_path=output_csv)
            stats = cleaner.clean_dataset()

            self.assertEqual(stats["raw_count"], 7)
            self.assertEqual(stats["exact_duplicates_removed"], 1)
            self.assertEqual(stats["url_duplicates_removed"], 1)
            self.assertEqual(stats["title_duplicates_removed"], 1)
            self.assertEqual(stats["missing_titles_removed"], 1)
            self.assertEqual(stats["too_short_titles_removed"], 1)
            self.assertEqual(stats["final_count"], 2)

            # Check output file
            with open(output_csv, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 2)
                # Verify date normalization in row 2
                self.assertEqual(rows[1]["date"], "2026-05-20")
                # Verify HTML stripped
                self.assertEqual(rows[1]["content"], "혁신 솔루션")


if __name__ == "__main__":
    unittest.main()
