"""Market & Competitor News Crawler for NovaFactory AI.

Collects market, competitor, technology, policy, and funding news/announcements
from public RSS feeds, web pages, and APIs according to logs/source_plan.md.
Falls back to fallback datasets if collection fails or count < target_count.
"""

import os
import sys
import re
import csv
import logging
import email.utils
from datetime import datetime
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Tuple, Optional

import requests
import yaml
from bs4 import BeautifulSoup

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "crawler.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MarketCrawler")


class MarketCrawler:
    """Crawler that gathers market, competitor, tech, and policy intelligence."""

    FIELDNAMES = [
        "article_id",
        "category",
        "title",
        "date",
        "content",
        "summary",
        "source_url",
        "source_name",
        "company_tag",
        "keywords",
        "collected_at",
        "has_null",
        "is_duplicate_seed",
        "data_origin"
    ]

    def __init__(
        self,
        config_path: str = "config/company_profile.yaml",
        fallback_path: str = "data/fallback/fallback_market_news.csv",
        output_path: str = "data/raw/crawled_market_news.csv",
        target_count: int = 200,
        request_timeout: int = 8
    ):
        self.config_path = config_path
        self.fallback_path = fallback_path
        self.output_path = output_path
        self.target_count = target_count
        self.request_timeout = request_timeout

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        # Results tracking
        self.crawled_articles: List[Dict[str, Any]] = []
        self.seen_urls = set()
        self.seen_titles = set()
        self.failed_sources: List[Tuple[str, str]] = []

        # Load configuration
        self.profile = self._load_profile()
        self.competitors = self.profile.get("competitors", [])
        self.interest_keywords = self.profile.get("interest_keywords", [])
        self.funding_keywords = self.profile.get("funding_keywords", [])

    def _load_profile(self) -> Dict[str, Any]:
        """Loads company profile configuration."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found at {self.config_path}. Using default profile.")
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error loading {self.config_path}: {e}")
            return {}

    def _clean_html(self, text: str) -> str:
        """Removes HTML tags and normalizes whitespace."""
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _parse_date(self, raw_date: str) -> str:
        """Normalizes various date formats to YYYY-MM-DD."""
        if not raw_date:
            return datetime.now().strftime("%Y-%m-%d")
        raw_date = raw_date.strip()
        # Try RFC 2822 (standard RSS)
        try:
            dt = email.utils.parsedate_to_datetime(raw_date)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
        # Try YYYY-MM-DD or ISO pattern
        m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw_date)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return datetime.now().strftime("%Y-%m-%d")

    def _classify_article(self, title: str, content: str) -> Tuple[str, str, str]:
        """Classifies article into category, matched company_tag, and pipe-separated keywords."""
        full_text = f"{title} {content}".lower()

        # Check competitors
        company_tag = ""
        matched_category = ""
        for comp in self.competitors:
            if comp.lower() in full_text:
                company_tag = comp
                matched_category = "competitor"
                break

        # Check funding keywords
        if not matched_category:
            for kw in self.funding_keywords:
                if kw.lower() in full_text:
                    matched_category = "funding"
                    break

        # Check policy keywords
        if not matched_category:
            for pkw in ["정책", "규제", "지원사업", "중기부", "과기정통부", "표준", "법안"]:
                if pkw in full_text:
                    matched_category = "policy"
                    break

        # Check technology keywords
        if not matched_category:
            for tkw in ["머신비전", "비전 ai", "알고리즘", "딥러닝", "엣지 ai", "불량 탐지", "검사"]:
                if tkw in full_text:
                    matched_category = "technology"
                    break

        if not matched_category:
            matched_category = "market"

        # Extract all matched keywords
        all_kw_pool = self.interest_keywords + self.funding_keywords + [
            "데이터", "보안", "생성형 AI", "디지털 전환", "클라우드", "자동화"
        ]
        matched_kws = [kw for kw in all_kw_pool if kw.lower() in full_text]
        # deduplicate while keeping order
        unique_kws = list(dict.fromkeys(matched_kws))
        keywords_str = "|".join(unique_kws) if unique_kws else "AI|스마트팩토리"

        return matched_category, company_tag, keywords_str

    def _add_article(
        self,
        title: str,
        link: str,
        pub_date: str,
        content: str,
        source_name: str,
        category: Optional[str] = None
    ) -> bool:
        """Helper to validate, deduplicate, and append article."""
        title = title.strip()
        link = link.strip()
        if not title or not link:
            return False

        # Deduplication check
        norm_title = re.sub(r"[\s\W_]+", "", title).lower()
        if link in self.seen_urls or norm_title in self.seen_titles:
            return False

        self.seen_urls.add(link)
        self.seen_titles.add(norm_title)

        date_str = self._parse_date(pub_date)
        clean_content = self._clean_html(content)
        summary = clean_content[:200] if len(clean_content) > 200 else clean_content

        auto_cat, comp_tag, kws = self._classify_article(title, clean_content)
        final_category = category if category else auto_cat

        idx = len(self.crawled_articles) + 1
        article = {
            "article_id": f"LIVE-{idx:04d}",
            "category": final_category,
            "title": title,
            "date": date_str,
            "content": clean_content if clean_content else title,
            "summary": summary if summary else title,
            "source_url": link,
            "source_name": source_name,
            "company_tag": comp_tag,
            "keywords": kws,
            "collected_at": datetime.now().isoformat(),
            "has_null": "false",
            "is_duplicate_seed": "false",
            "data_origin": "live_crawler"
        }
        self.crawled_articles.append(article)
        return True

    def _fetch_rss(self, source_name: str, url: str, default_category: Optional[str] = None) -> int:
        """Fetches and parses standard RSS or Atom XML feeds."""
        logger.info(f"Fetching RSS: [{source_name}] -> {url[:70]}...")
        count = 0
        try:
            r = requests.get(url, headers=self.headers, timeout=self.request_timeout)
            if r.status_code != 200:
                msg = f"HTTP {r.status_code}"
                logger.warning(f"Source [{source_name}] returned {msg}")
                self.failed_sources.append((source_name, msg))
                return 0

            root = ET.fromstring(r.content)

            # Atom feed handling
            if root.tag.endswith("feed"):
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in root.findall("atom:entry", ns):
                    title_el = entry.find("atom:title", ns)
                    title = title_el.text.strip() if title_el is not None and title_el.text else ""
                    link_el = entry.find("atom:link", ns)
                    link = link_el.attrib.get("href", "") if link_el is not None else ""
                    updated_el = entry.find("atom:updated", ns)
                    pub_date = updated_el.text if updated_el is not None else ""
                    summary_el = entry.find("atom:summary", ns)
                    content = summary_el.text if summary_el is not None and summary_el.text else title

                    if self._add_article(title, link, pub_date, content, source_name, default_category):
                        count += 1
            else:
                # RSS 2.0 handling
                items = root.findall(".//item")
                for item in items:
                    title_el = item.find("title")
                    title = title_el.text.strip() if title_el is not None and title_el.text else ""
                    link_el = item.find("link")
                    link = link_el.text.strip() if link_el is not None and link_el.text else ""
                    pub_date_el = item.find("pubDate")
                    pub_date = pub_date_el.text if pub_date_el is not None else ""
                    desc_el = item.find("description")
                    content = desc_el.text if desc_el is not None and desc_el.text else title

                    # Specific source tag in Google News
                    source_el = item.find("source")
                    src_label = source_el.text.strip() if source_el is not None and source_el.text else source_name

                    if self._add_article(title, link, pub_date, content, src_label, default_category):
                        count += 1

            logger.info(f"Source [{source_name}] collected {count} articles. (Total: {len(self.crawled_articles)})")
            return count

        except Exception as e:
            msg = f"Exception: {str(e)}"
            logger.error(f"Error fetching [{source_name}]: {msg}")
            self.failed_sources.append((source_name, msg))
            return 0

    def _fetch_mss_press(self) -> int:
        """Fetches press releases from Ministry of SMEs and Startups (중소벤처기업부)."""
        source_name = "중소벤처기업부 보도자료"
        url = "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=86"
        logger.info(f"Scraping Web: [{source_name}] -> {url}...")
        count = 0
        try:
            r = requests.get(url, headers=self.headers, timeout=self.request_timeout)
            if r.status_code != 200:
                self.failed_sources.append((source_name, f"HTTP {r.status_code}"))
                return 0

            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("table tbody tr")
            for row in rows:
                title_el = row.select_one("td.subject a, td a")
                date_el = row.select_one("td:nth-child(5), td:nth-child(4)")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                link = urllib.parse.urljoin(url, href) if href else url
                pub_date = date_el.get_text(strip=True) if date_el else ""

                if self._add_article(title, link, pub_date, title, source_name, "policy"):
                    count += 1

            logger.info(f"Source [{source_name}] collected {count} articles. (Total: {len(self.crawled_articles)})")
            return count

        except Exception as e:
            self.failed_sources.append((source_name, f"Exception: {str(e)}"))
            logger.error(f"Error scraping [{source_name}]: {e}")
            return 0

    def _fetch_korea_briefing(self) -> int:
        """Fetches policy news from korea.kr 정책브리핑 (대체 소스)."""
        source_name = "대한민국 정책브리핑"
        url = "https://www.korea.kr/briefing/pressReleaseList.do"
        logger.info(f"Scraping Web (대체 소스): [{source_name}] -> {url}...")
        count = 0
        try:
            r = requests.get(url, headers=self.headers, timeout=self.request_timeout)
            if r.status_code != 200:
                self.failed_sources.append((source_name, f"HTTP {r.status_code}"))
                return 0

            soup = BeautifulSoup(r.text, "html.parser")
            links = soup.select("div.article_list li a, ul.list_type li a, table tbody tr td a")
            for link_el in links:
                title = link_el.get_text(strip=True)
                if len(title) < 10:
                    continue
                href = link_el.get("href", "")
                link = urllib.parse.urljoin(url, href) if href else url
                if self._add_article(title, link, "", title, source_name, "policy"):
                    count += 1
            logger.info(f"Source [{source_name}] collected {count} articles. (Total: {len(self.crawled_articles)})")
            return count
        except Exception as e:
            self.failed_sources.append((source_name, f"Exception: {str(e)}"))
            logger.error(f"Error scraping [{source_name}]: {e}")
            return 0

    def run_crawling(self) -> None:
        """Executes the full multi-tier crawling pipeline."""
        logger.info("=== Starting Market News Crawling Pipeline ===")

        # 1. Primary Sources (from source_plan.md)
        primary_sources = [
            (
                "Google News RSS (제조 AX / 스마트팩토리)",
                "https://news.google.com/rss/search?q="
                + urllib.parse.quote('스마트팩토리 OR "제조 AX" OR "AI 품질검사"')
                + "&hl=ko&gl=KR&ceid=KR:ko",
                "market"
            ),
            (
                "Google News RSS (경쟁사 / 머신비전)",
                "https://news.google.com/rss/search?q="
                + urllib.parse.quote('"VisionForge" OR "InspectAI" OR "FactoryMind" OR "QualiBot" OR "머신비전"')
                + "&hl=ko&gl=KR&ceid=KR:ko",
                "competitor"
            ),
            (
                "Google News RSS (정부지원 / AI 바우처)",
                "https://news.google.com/rss/search?q="
                + urllib.parse.quote('"스마트공장" OR "AI 바우처" OR "중소기업 지원"')
                + "&hl=ko&gl=KR&ceid=KR:ko",
                "funding"
            ),
            (
                "Google News RSS (비전 AI / 기술동향)",
                "https://news.google.com/rss/search?q="
                + urllib.parse.quote('"비전 AI" OR "불량 탐지" OR "엣지 AI"')
                + "&hl=ko&gl=KR&ceid=KR:ko",
                "technology"
            ),
            (
                "AI타임스 종합 RSS",
                "https://www.aitimes.com/rss/allArticle.xml",
                "technology"
            ),
            (
                "전자신문 산업/경제 RSS",
                "https://rss.etnews.com/Section901.xml",
                "market"
            ),
            (
                "전자신문 SW/신산업 RSS",
                "https://rss.etnews.com/Section902.xml",
                "technology"
            ),
            (
                "GeekNews 기술 피드",
                "https://news.hada.io/rss/news",
                "technology"
            )
        ]

        # Execute primary RSS feeds (with fault tolerance)
        for name, url, cat in primary_sources:
            try:
                self._fetch_rss(name, url, default_category=cat)
            except Exception as e:
                logger.error(f"Unexpected error in source {name}: {e}")
                self.failed_sources.append((name, str(e)))

        # Web scraping source
        try:
            self._fetch_mss_press()
        except Exception as e:
            logger.error(f"Unexpected error in MSS web scraping: {e}")
            self.failed_sources.append(("중소벤처기업부 보도자료", str(e)))

        # 2. Check threshold & execute alternate sources if < target_count
        if len(self.crawled_articles) < self.target_count:
            logger.warning(
                f"Collected {len(self.crawled_articles)} articles, which is less than "
                f"target {self.target_count}. Triggering alternate sources..."
            )

            alternate_sources = [
                (
                    "Google News RSS (대체: 스마트제조 & 공정 자동화)",
                    "https://news.google.com/rss/search?q="
                    + urllib.parse.quote('"스마트제조" OR "공정 자동화" OR "산업 AX"')
                    + "&hl=ko&gl=KR&ceid=KR:ko",
                    "market"
                ),
                (
                    "Google News RSS (대체: 인공지능 불량검사)",
                    "https://news.google.com/rss/search?q="
                    + urllib.parse.quote('"인공지능 불량검사" OR "머신비전 카메라"')
                    + "&hl=ko&gl=KR&ceid=KR:ko",
                    "technology"
                )
            ]

            for name, url, cat in alternate_sources:
                self._fetch_rss(name, url, default_category=cat)
                if len(self.crawled_articles) >= self.target_count:
                    break

            if len(self.crawled_articles) < self.target_count:
                self._fetch_korea_briefing()

        # 3. Check threshold & merge fallback dataset if still < target_count
        live_count = len(self.crawled_articles)
        fallback_count = 0

        if live_count < self.target_count:
            logger.warning(
                f"Live articles ({live_count}) still below target ({self.target_count}). "
                f"Merging fallback dataset from {self.fallback_path}..."
            )
            fallback_count = self._merge_fallback()
        else:
            logger.info(
                f"Live articles count ({live_count}) successfully met target ({self.target_count}). "
                f"No fallback merging required."
            )

        # 4. Save to CSV
        self._save_to_csv()

        # 5. Output Summary
        self._print_summary(live_count, fallback_count)
        return {
            "total_count": len(self.crawled_articles),
            "live_count": live_count,
            "fallback_count": fallback_count,
            "failed_sources": self.failed_sources
        }

    def crawl(self) -> Dict[str, Any]:
        """Alias for run_crawling."""
        return self.run_crawling()

    def _merge_fallback(self) -> int:
        """Merges fallback dataset until target count is satisfied or full file is incorporated."""
        if not os.path.exists(self.fallback_path):
            logger.error(f"Fallback file not found: {self.fallback_path}")
            return 0

        added = 0
        try:
            with open(self.fallback_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Enforce data_origin tag
                    row["data_origin"] = "synthetic_fallback"
                    url = row.get("source_url", "")
                    if url and url in self.seen_urls:
                        continue
                    if url:
                        self.seen_urls.add(url)
                    self.crawled_articles.append(row)
                    added += 1
                    if len(self.crawled_articles) >= self.target_count:
                        break

            logger.info(f"Merged {added} fallback articles. Total is now {len(self.crawled_articles)}.")
            return added
        except Exception as e:
            logger.error(f"Failed to merge fallback CSV: {e}")
            return 0

    def _save_to_csv(self) -> None:
        """Saves all articles to output CSV."""
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        try:
            with open(self.output_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()
                for row in self.crawled_articles:
                    writer.writerow(row)
            logger.info(f"Successfully saved {len(self.crawled_articles)} articles to {self.output_path}")
        except Exception as e:
            logger.error(f"Failed to write CSV to {self.output_path}: {e}")
            raise

    def _print_summary(self, live_count: int, fallback_count: int) -> None:
        """Prints a human-readable execution summary."""
        total = len(self.crawled_articles)
        cat_counts: Dict[str, int] = {}
        for a in self.crawled_articles:
            cat = a.get("category", "unknown")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        print("\n" + "=" * 60)
        print("          MARKET CRAWLER EXECUTION REPORT")
        print("=" * 60)
        print(f"Total Collected Articles : {total} (Target: {self.target_count})")
        print(f" - Live Collected Count  : {live_count}")
        print(f" - Fallback Merged Count : {fallback_count}")
        print(f" - Target Met            : {'SUCCESS (>= 200)' if total >= 200 else 'FAILED (< 200)'}")
        print("-" * 60)
        print("Category Distribution:")
        for cat, cnt in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True):
            print(f" - {cat:15} : {cnt} articles")
        print("-" * 60)
        print(f"Failed Sources ({len(self.failed_sources)}):")
        if self.failed_sources:
            for sname, reason in self.failed_sources:
                print(f" [X] {sname}: {reason}")
        else:
            print(" (None - All attempted sources succeeded)")
        print("-" * 60)
        print(f"Output File: {self.output_path}")
        print(f"Log File   : {LOG_FILE}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    crawler = MarketCrawler()
    crawler.run_crawling()
