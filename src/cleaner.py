"""Market Data Cleaner for project1-market-agent.

Cleans raw collected market news:
- Removes HTML tags and unescapes HTML entities.
- Cleans and normalizes whitespace.
- Filters out empty or excessively short titles.
- Normalizes dates to YYYY-MM-DD.
- Removes exact row duplicates, URL duplicates, title duplicates, and article_id duplicates.
- Saves cleaned dataset to data/processed/cleaned_market_news.csv.
"""

import os
import sys
import re
import csv
import html
import logging
import email.utils
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Set

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "cleaner.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MarketCleaner")


class MarketDataCleaner:
    """ETL cleaner for market intelligence datasets."""

    MIN_TITLE_LENGTH = 5

    def __init__(
        self,
        input_path: str = "data/raw/crawled_market_news.csv",
        output_path: str = "data/processed/cleaned_market_news.csv",
        min_title_length: int = 5
    ):
        self.input_path = input_path
        self.output_path = output_path
        self.min_title_length = min_title_length

    @staticmethod
    def clean_text(text: Optional[str]) -> str:
        """Removes HTML tags, unescapes HTML entities, and normalizes whitespaces."""
        if not text:
            return ""
        # 1. Unescape HTML entities (e.g. &nbsp; &quot; &amp; &#39;)
        cleaned = html.unescape(text)
        # 2. Remove HTML tags
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        # 3. Replace non-breaking spaces and zero-width spaces
        cleaned = cleaned.replace("\u00a0", " ").replace("\u200b", " ")
        # 4. Collapse multiple whitespaces/newlines into a single space
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def normalize_date(raw_date: Optional[str], fallback_date: Optional[str] = None) -> str:
        """Normalizes date string to standard YYYY-MM-DD format."""
        today_str = fallback_date or datetime.now().strftime("%Y-%m-%d")
        if not raw_date:
            return today_str

        raw_date = raw_date.strip()

        # Check standard YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
            return raw_date

        # Try RFC 2822 format (e.g., 'Sat, 19 Sep 2026 00:15:55 GMT')
        try:
            dt = email.utils.parsedate_to_datetime(raw_date)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        # Try regex patterns like YYYY-MM-DDTHH:MM:SS, YYYY.MM.DD, YYYY/MM/DD, YYYY년 MM월 DD일
        m = re.search(r"(\d{4})[-/.년\s]+(\d{1,2})[-/.월\s]+(\d{1,2})", raw_date)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"

        # If ISO format (e.g. 2026-09-19T14:00:00)
        try:
            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        return today_str

    def is_valid_title(self, title: Optional[str]) -> bool:
        """Validates that title is not empty, meets minimum length, and contains meaningful text."""
        if not title:
            return False
        cleaned = self.clean_text(title)
        if len(cleaned) < self.min_title_length:
            return False
        # Must contain at least one alphanumeric or Korean/CJK character
        if not re.search(r"[a-zA-Z0-9가-힣]", cleaned):
            return False
        return True

    @staticmethod
    def normalize_title_for_dedup(title: str) -> str:
        """Creates a normalized string representation of title for fuzzy duplicate detection."""
        # Lowercase, remove whitespace and non-alphanumeric/non-Korean characters
        return re.sub(r"[\s\W_]+", "", title).lower()

    @staticmethod
    def normalize_url_for_dedup(url: str) -> str:
        """Normalizes URL for duplicate detection (removes trailing slashes and common tracking params)."""
        url = url.strip()
        # Remove trailing slash
        url = re.sub(r"/+$", "", url)
        # Normalize URL scheme
        return url.lower()

    def clean_dataset(self) -> Dict[str, Any]:
        """Executes full cleaning pipeline and saves output."""
        logger.info(f"=== Starting Market Data Cleaning Pipeline ===")
        logger.info(f"Input file : {self.input_path}")
        logger.info(f"Output file: {self.output_path}")

        if not os.path.exists(self.input_path):
            raise FileNotFoundError(f"Input file not found: {self.input_path}")

        # 1. Read Raw CSV
        with open(self.input_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            raw_rows = list(reader)

        raw_count = len(raw_rows)
        logger.info(f"Raw data loaded: {raw_count} rows, Columns: {fieldnames}")

        # Metrics tracking
        exact_dups = 0
        missing_titles = 0
        too_short_titles = 0
        url_dups = 0
        title_dups = 0
        id_dups = 0

        seen_exact_hashes: Set[str] = set()
        seen_urls: Set[str] = set()
        seen_titles: Set[str] = set()
        seen_ids: Set[str] = set()

        cleaned_rows: List[Dict[str, Any]] = []

        for row_idx, row in enumerate(raw_rows):
            # 2. Check exact duplicate
            row_hash = "|".join(str(row.get(col, "")) for col in fieldnames)
            if row_hash in seen_exact_hashes:
                exact_dups += 1
                continue
            seen_exact_hashes.add(row_hash)

            # 3. Clean Text & Validate Title
            raw_title = row.get("title", "")
            cleaned_title = self.clean_text(raw_title)

            if not cleaned_title:
                missing_titles += 1
                logger.debug(f"Row {row_idx}: Dropped due to empty title")
                continue

            if not self.is_valid_title(cleaned_title):
                too_short_titles += 1
                logger.debug(f"Row {row_idx}: Dropped due to invalid/short title: '{cleaned_title}'")
                continue

            # 4. Clean content, summary, source_name
            cleaned_content = self.clean_text(row.get("content", ""))
            cleaned_summary = self.clean_text(row.get("summary", ""))
            cleaned_source_name = self.clean_text(row.get("source_name", "기타 뉴스"))

            # Fill missing content/summary
            if not cleaned_content and cleaned_summary:
                cleaned_content = cleaned_summary
            elif not cleaned_content:
                cleaned_content = cleaned_title

            if not cleaned_summary and cleaned_content:
                cleaned_summary = cleaned_content[:200]
            elif not cleaned_summary:
                cleaned_summary = cleaned_title

            # 5. Normalize Date
            normalized_date = self.normalize_date(row.get("date"), fallback_date=row.get("collected_at", "")[:10])

            # 6. Deduplication: URL Check
            raw_url = row.get("source_url", "").strip()
            norm_url = self.normalize_url_for_dedup(raw_url)
            if norm_url:
                if norm_url in seen_urls:
                    url_dups += 1
                    continue
                seen_urls.add(norm_url)

            # 7. Deduplication: Title Check
            norm_title = self.normalize_title_for_dedup(cleaned_title)
            if norm_title in seen_titles:
                title_dups += 1
                continue
            seen_titles.add(norm_title)

            # 8. Deduplication: Article ID Check
            raw_id = row.get("article_id", "").strip()
            if raw_id:
                if raw_id in seen_ids:
                    id_dups += 1
                    continue
                seen_ids.add(raw_id)
            else:
                raw_id = f"CLN-{len(cleaned_rows)+1:04d}"
                seen_ids.add(raw_id)

            # Prepare cleaned row
            cleaned_row = dict(row)
            cleaned_row["article_id"] = raw_id
            cleaned_row["title"] = cleaned_title
            cleaned_row["content"] = cleaned_content
            cleaned_row["summary"] = cleaned_summary
            cleaned_row["source_name"] = cleaned_source_name
            cleaned_row["source_url"] = raw_url
            cleaned_row["date"] = normalized_date
            cleaned_row["has_null"] = "false"
            cleaned_row["is_duplicate_seed"] = "false"

            cleaned_rows.append(cleaned_row)

        # 9. Save to output CSV
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in cleaned_rows:
                writer.writerow(r)

        final_count = len(cleaned_rows)
        total_dups_removed = exact_dups + url_dups + title_dups + id_dups
        total_missing_removed = missing_titles + too_short_titles

        stats = {
            "raw_count": raw_count,
            "final_count": final_count,
            "exact_duplicates_removed": exact_dups,
            "url_duplicates_removed": url_dups,
            "title_duplicates_removed": title_dups,
            "id_duplicates_removed": id_dups,
            "total_duplicates_removed": total_dups_removed,
            "missing_titles_removed": missing_titles,
            "too_short_titles_removed": too_short_titles,
            "total_missing_invalid_removed": total_missing_removed,
            "output_path": self.output_path
        }

        logger.info(
            f"Cleaning completed: Raw={raw_count} -> Final={final_count} "
            f"(Dups removed={total_dups_removed}, Missing/Invalid removed={total_missing_removed})"
        )
        self._print_report(stats)
        return stats

    def _print_report(self, stats: Dict[str, Any]) -> None:
        """Prints formatted execution report."""
        print("\n" + "=" * 60)
        print("          MARKET DATA CLEANER REPORT")
        print("=" * 60)
        print(f"Raw Input Rows          : {stats['raw_count']}")
        print(f"Final Cleaned Rows      : {stats['final_count']}")
        print("-" * 60)
        print("Duplicates Removed Details:")
        print(f" - Exact Row Duplicates : {stats['exact_duplicates_removed']}")
        print(f" - URL Duplicates       : {stats['url_duplicates_removed']}")
        print(f" - Title Duplicates     : {stats['title_duplicates_removed']}")
        print(f" - Article ID Duplicates: {stats['id_duplicates_removed']}")
        print(f" > Total Duplicates     : {stats['total_duplicates_removed']}")
        print("-" * 60)
        print("Missing/Invalid Filtered Details:")
        print(f" - Missing Titles       : {stats['missing_titles_removed']}")
        print(f" - Too Short Titles     : {stats['too_short_titles_removed']}")
        print(f" > Total Invalid Removed: {stats['total_missing_invalid_removed']}")
        print("-" * 60)
        print(f"Output File: {stats['output_path']}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    cleaner = MarketDataCleaner()
    cleaner.clean_dataset()
