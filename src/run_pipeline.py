"""End-to-End Orchestrator Pipeline for NovaFactory AI Market Agent.

Orchestrates the entire market intelligence workflow:
1. Crawler     : Multi-tier RSS & Web scraping with fault tolerance and fallback merging.
2. Cleaner     : HTML stripping, entity unescaping, title/date normalization, deduplication.
3. Recommender : Multi-factor scoring (keyword/company/competitor/funding/recency) & recommendation reasons.
4. Dashboard   : GitHub Pages static site (docs/index.html) and JSON analytical report (docs/report.json).

Records stage status: SUCCESS / WARNING / FAILED.
Outputs comprehensive logs to logs/pipeline.log.
"""

import os
import sys
import time
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, List

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.crawler import MarketCrawler
from src.cleaner import MarketDataCleaner
from src.recommender import MarketRecommender
from src.build_site import DashboardBuilder

# Setup pipeline logger
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "pipeline.log")

# Configure logger
logger = logging.getLogger("MarketPipeline")
logger.setLevel(logging.INFO)
logger.handlers.clear()

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s"))
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(stream_handler)


class MarketPipeline:
    """Orchestrates market agent workflow with robust error handling and status tracking."""

    def __init__(
        self,
        config_path: str = "config/company_profile.yaml",
        raw_csv: str = "data/raw/crawled_market_news.csv",
        fallback_csv: str = "data/fallback/fallback_market_news.csv",
        cleaned_csv: str = "data/processed/cleaned_market_news.csv",
        recommended_csv: str = "data/processed/recommended_market_news.csv",
        docs_dir: str = "docs",
        target_count: int = 200
    ):
        self.config_path = os.path.join(PROJECT_ROOT, config_path)
        self.raw_csv = os.path.join(PROJECT_ROOT, raw_csv)
        self.fallback_csv = os.path.join(PROJECT_ROOT, fallback_csv)
        self.cleaned_csv = os.path.join(PROJECT_ROOT, cleaned_csv)
        self.recommended_csv = os.path.join(PROJECT_ROOT, recommended_csv)
        self.docs_dir = os.path.join(PROJECT_ROOT, docs_dir)
        self.target_count = target_count

        self.stages: Dict[str, Dict[str, Any]] = {}
        self.start_time: float = 0.0

    def record_stage(self, stage_name: str, status: str, details: str, duration: float) -> None:
        """Records stage result and logs outcome."""
        self.stages[stage_name] = {
            "status": status,
            "details": details,
            "duration": f"{duration:.2f}s"
        }
        if status == "SUCCESS":
            logger.info(f"[{stage_name}] Status: SUCCESS - {details} (Elapsed: {duration:.2f}s)")
        elif status == "WARNING":
            logger.warning(f"[{stage_name}] Status: WARNING - {details} (Elapsed: {duration:.2f}s)")
        else:
            logger.error(f"[{stage_name}] Status: FAILED - {details} (Elapsed: {duration:.2f}s)")

    def run_stage_crawler(self) -> bool:
        """Executes Stage 1: Market Crawler."""
        stage_name = "1. CRAWLER"
        t0 = time.time()
        logger.info(f"Starting {stage_name} (Target: >= {self.target_count} articles)...")

        try:
            crawler = MarketCrawler(
                config_path=self.config_path,
                fallback_path=self.fallback_csv,
                output_path=self.raw_csv,
                target_count=self.target_count
            )
            result = crawler.crawl()
            duration = time.time() - t0

            total = result.get("total_count", 0)
            live = result.get("live_count", 0)
            fallback = result.get("fallback_count", 0)
            failed_sources = result.get("failed_sources", [])

            if total >= self.target_count:
                if len(failed_sources) == 0 and fallback == 0:
                    status = "SUCCESS"
                    msg = f"Collected {total} articles (Live: {live}, Fallback: {fallback}, Failed Sources: 0)"
                else:
                    status = "WARNING"
                    msg = (
                        f"Collected {total} articles with warnings "
                        f"(Live: {live}, Fallback: {fallback}, Failed Sources: {len(failed_sources)})"
                    )
                self.record_stage(stage_name, status, msg, duration)
                return True
            else:
                status = "WARNING" if total > 0 else "FAILED"
                msg = f"Only {total} articles collected (Target was {self.target_count})"
                self.record_stage(stage_name, status, msg, duration)
                return total > 0

        except Exception as e:
            duration = time.time() - t0
            logger.error(f"Crawler unhandled exception: {e}\n{traceback.format_exc()}")
            # Attempt emergency fallback load if raw file doesn't exist
            if not os.path.exists(self.raw_csv) and os.path.exists(self.fallback_csv):
                logger.warning(f"Emergency copying fallback data to {self.raw_csv} due to crawler crash...")
                import shutil
                shutil.copyfile(self.fallback_csv, self.raw_csv)
                self.record_stage(
                    stage_name,
                    "WARNING",
                    f"Crawler crashed ({e}), recovered with emergency fallback copy",
                    duration
                )
                return True

            self.record_stage(stage_name, "FAILED", f"Crawler failed with exception: {str(e)}", duration)
            return False

    def run_stage_cleaner(self) -> bool:
        """Executes Stage 2: Data Cleaner."""
        stage_name = "2. CLEANER"
        t0 = time.time()
        logger.info(f"Starting {stage_name}...")

        if not os.path.exists(self.raw_csv):
            duration = time.time() - t0
            self.record_stage(stage_name, "FAILED", f"Input file missing: {self.raw_csv}", duration)
            return False

        try:
            cleaner = MarketDataCleaner(
                input_path=self.raw_csv,
                output_path=self.cleaned_csv
            )
            stats = cleaner.clean_dataset()
            duration = time.time() - t0

            raw_cnt = stats["raw_count"]
            final_cnt = stats["final_count"]
            dups = stats["total_duplicates_removed"]
            invalids = stats["total_missing_invalid_removed"]

            if final_cnt >= self.target_count:
                status = "SUCCESS"
                msg = f"Cleaned {final_cnt} articles (Raw: {raw_cnt}, Dups Removed: {dups}, Filtered: {invalids})"
            elif final_cnt > 0:
                status = "WARNING"
                msg = f"Cleaned {final_cnt} articles (below target {self.target_count})"
            else:
                status = "FAILED"
                msg = "No articles remained after cleaning"

            self.record_stage(stage_name, status, msg, duration)
            return final_cnt > 0

        except Exception as e:
            duration = time.time() - t0
            logger.error(f"Cleaner unhandled exception: {e}\n{traceback.format_exc()}")
            self.record_stage(stage_name, "FAILED", f"Cleaner failed: {str(e)}", duration)
            return False

    def run_stage_recommender(self) -> bool:
        """Executes Stage 3: Market Recommender."""
        stage_name = "3. RECOMMENDER"
        t0 = time.time()
        logger.info(f"Starting {stage_name}...")

        if not os.path.exists(self.cleaned_csv):
            duration = time.time() - t0
            self.record_stage(stage_name, "FAILED", f"Input file missing: {self.cleaned_csv}", duration)
            return False

        try:
            recommender = MarketRecommender(
                config_path=self.config_path,
                input_path=self.cleaned_csv,
                output_path=self.recommended_csv,
                top_n=30
            )
            top_items = recommender.run_recommendation()
            duration = time.time() - t0

            count = len(top_items)
            top_score = top_items[0].get("score", 0) if count > 0 else 0
            llm_mode = recommender.use_llm

            if count >= 30:
                status = "SUCCESS"
                msg = f"Generated {count} recommendations (Top Score: {top_score}, LLM: {llm_mode})"
            elif count > 0:
                status = "WARNING"
                msg = f"Generated {count} recommendations (fewer than 30)"
            else:
                status = "FAILED"
                msg = "No recommendations generated"

            self.record_stage(stage_name, status, msg, duration)
            return count > 0

        except Exception as e:
            duration = time.time() - t0
            logger.error(f"Recommender unhandled exception: {e}\n{traceback.format_exc()}")
            self.record_stage(stage_name, "FAILED", f"Recommender failed: {str(e)}", duration)
            return False

    def run_stage_dashboard(self) -> bool:
        """Executes Stage 4: Dashboard Site Builder."""
        stage_name = "4. DASHBOARD"
        t0 = time.time()
        logger.info(f"Starting {stage_name}...")

        if not os.path.exists(self.recommended_csv):
            duration = time.time() - t0
            self.record_stage(stage_name, "FAILED", f"Input file missing: {self.recommended_csv}", duration)
            return False

        try:
            builder = DashboardBuilder(
                config_path=self.config_path,
                recommended_csv=self.recommended_csv,
                cleaned_csv=self.cleaned_csv,
                output_dir=self.docs_dir
            )
            builder.build()
            duration = time.time() - t0

            html_file = os.path.join(self.docs_dir, "index.html")
            json_file = os.path.join(self.docs_dir, "report.json")

            if os.path.exists(html_file) and os.path.exists(json_file):
                status = "SUCCESS"
                msg = f"Dashboard built: {html_file} ({os.path.getsize(html_file):,} bytes) & {json_file}"
            else:
                status = "FAILED"
                msg = "Failed to produce index.html or report.json"

            self.record_stage(stage_name, status, msg, duration)
            return status == "SUCCESS"

        except Exception as e:
            duration = time.time() - t0
            logger.error(f"Dashboard builder unhandled exception: {e}\n{traceback.format_exc()}")
            self.record_stage(stage_name, "FAILED", f"Dashboard builder failed: {str(e)}", duration)
            return False

    def print_pipeline_summary(self, overall_success: bool) -> None:
        """Prints a comprehensive end-of-pipeline summary."""
        total_duration = time.time() - self.start_time

        print("\n" + "=" * 80)
        print("               MARKET AGENT PIPELINE EXECUTION SUMMARY")
        print("=" * 80)
        print(f"{'Stage':16} | {'Status':8} | {'Duration':8} | {'Details'}")
        print("-" * 80)

        for name, info in self.stages.items():
            status = info["status"]
            dur = info["duration"]
            det = info["details"]
            print(f"{name:16} | {status:8} | {dur:8} | {det}")

        print("-" * 80)
        overall_str = "SUCCESS" if overall_success else "FAILED / PARTIAL"
        print(f"Overall Result   : {overall_str} (Total Elapsed: {total_duration:.2f}s)")
        print(f"Artifacts Created:")
        print(f" - Raw Data      : {self.raw_csv}")
        print(f" - Cleaned Data  : {self.cleaned_csv}")
        print(f" - Recommended   : {self.recommended_csv}")
        print(f" - Dashboard     : {os.path.join(self.docs_dir, 'index.html')}")
        print(f" - Report JSON   : {os.path.join(self.docs_dir, 'report.json')}")
        print(f"Log File         : {LOG_FILE}")
        print("=" * 80 + "\n")

    def run(self) -> bool:
        """Executes the entire end-to-end pipeline in sequential order."""
        self.start_time = time.time()
        logger.info("================================================================================")
        logger.info(">>> STARTING NOVAFACTORY AI MARKET AGENT END-TO-END PIPELINE <<<")
        logger.info("================================================================================")

        # 1. Crawler
        crawl_ok = self.run_stage_crawler()
        # Even if crawler had partial failure, we proceed if raw CSV exists
        if not crawl_ok and not os.path.exists(self.raw_csv):
            logger.error("Pipeline aborted: Crawling failed completely and no raw/fallback CSV exists.")
            self.print_pipeline_summary(False)
            return False

        # 2. Cleaner
        clean_ok = self.run_stage_cleaner()
        if not clean_ok and not os.path.exists(self.cleaned_csv):
            logger.error("Pipeline aborted: Cleaning stage failed and no cleaned CSV exists.")
            self.print_pipeline_summary(False)
            return False

        # 3. Recommender
        recom_ok = self.run_stage_recommender()
        if not recom_ok and not os.path.exists(self.recommended_csv):
            logger.error("Pipeline aborted: Recommendation stage failed and no recommended CSV exists.")
            self.print_pipeline_summary(False)
            return False

        # 4. Dashboard
        dash_ok = self.run_stage_dashboard()

        overall_success = crawl_ok and clean_ok and recom_ok and dash_ok
        self.print_pipeline_summary(overall_success)

        return overall_success


if __name__ == "__main__":
    pipeline = MarketPipeline()
    success = pipeline.run()
    sys.exit(0 if success else 1)
