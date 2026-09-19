"""
Market & Competitor Intelligence Data Cleaner (시장·경쟁사·정책 데이터 정제기)

- 원본 입력: data/raw/crawled_market_news.csv
- 정제 출력: data/processed/cleaned_market_news.csv
- 주요 기능:
  1. HTML 태그 및 엔티티, 불필요 공백/제어문자 제거
  2. 제목(title) 결측치 및 지나치게 짧은 무효 데이터 필터링
  3. 날짜 형식 표준화 (YYYY-MM-DD)
  4. 다단계 중복 제거 (완전 중복, URL 중복, 정규화 제목 중복)
  5. 고유 article_id 부여 및 스키마 검증
"""

import os
import sys
import csv
import re
import html
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional
from email.utils import parsedate_to_datetime

# Windows 콘솔 출력 인코딩 안전화
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 로깅 설정
# ---------------------------------------------------------------------------
def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "cleaner.log"

    logger = logging.getLogger("DataCleaner")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # 콘솔 핸들러
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # 파일 핸들러
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# MarketNewsCleaner 클래스
# ---------------------------------------------------------------------------
class MarketNewsCleaner:
    def __init__(self, base_dir: Path = None):
        if base_dir is None:
            current_file = Path(__file__).resolve()
            if (current_file.parent.parent / "data" / "raw").exists():
                self.base_dir = current_file.parent.parent
            elif (current_file.parent.parent / "project1" / "data" / "raw").exists():
                self.base_dir = current_file.parent.parent / "project1"
            else:
                self.base_dir = Path.cwd()
        else:
            self.base_dir = base_dir

        self.raw_file = self.base_dir / "data" / "raw" / "crawled_market_news.csv"
        self.processed_dir = self.base_dir / "data" / "processed"
        self.output_file = self.processed_dir / "cleaned_market_news.csv"
        self.log_dir = self.base_dir / "logs"

        self.logger = setup_logging(self.log_dir)

        # 통계 카운터
        self.stats = {
            "raw_count": 0,
            "cleaned_count": 0,
            "missing_title_dropped": 0,
            "short_title_dropped": 0,
            "invalid_url_dropped": 0,
            "exact_duplicate_dropped": 0,
            "url_duplicate_dropped": 0,
            "title_duplicate_dropped": 0,
            "html_cleaned_count": 0,
            "date_normalized_count": 0,
        }

    # -----------------------------------------------------------------------
    # 1. 텍스트 정제 (HTML 태그, 엔티티, 불필요 공백)
    # -----------------------------------------------------------------------
    def clean_text(self, text: Optional[str]) -> str:
        """HTML 태그, HTML 엔티티, 제어문자 및 다중 공백 정제"""
        if text is None:
            return ""

        # 1. HTML 엔티티 디코딩 (&quot;, &amp;, &lt;, &gt;, &#39;, &nbsp; 등)
        cleaned = html.unescape(str(text))

        # 2. HTML 태그 제거
        has_tag = bool(re.search(r"<[^>]+>", cleaned))
        if has_tag:
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)

        # 3. 비가시 제어문자 및 특수 공백 제거
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\ufeff]", "", cleaned)

        # 4. 개행 및 연속된 공백을 단일 공백으로 치환
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned

    # -----------------------------------------------------------------------
    # 2. 날짜 정규화 (YYYY-MM-DD)
    # -----------------------------------------------------------------------
    def normalize_date(self, raw_date: Optional[str], fallback_date: Optional[str] = None) -> str:
        """다양한 날짜 형식을 표준 YYYY-MM-DD 형식으로 변환"""
        if not raw_date:
            if fallback_date:
                return self.normalize_date(fallback_date)
            return datetime.now().strftime("%Y-%m-%d")

        raw_date = str(raw_date).strip()

        # 이미 YYYY-MM-DD 형식인지 확인
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
            return raw_date

        # ISO 8601 포맷 (예: 2026-09-19T14:44:20+09:00)
        match_iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})T", raw_date)
        if match_iso:
            return f"{match_iso.group(1)}-{match_iso.group(2)}-{match_iso.group(3)}"

        # RFC 822 포맷 (예: 'Mon, 15 Sep 2026 09:00:00 GMT')
        try:
            dt = parsedate_to_datetime(raw_date)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        # YYYY.MM.DD 또는 YYYY/MM/DD 또는 YYYY MM DD
        match_dots = re.search(r"(\d{4})[./\s](\d{1,2})[./\s](\d{1,2})", raw_date)
        if match_dots:
            y, m, d = match_dots.groups()
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

        # 한글 포맷 (예: 2026년 9월 15일)
        match_kr = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", raw_date)
        if match_kr:
            y, m, d = match_kr.groups()
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

        # Fallback date 처리
        if fallback_date:
            return self.normalize_date(fallback_date)

        return datetime.now().strftime("%Y-%m-%d")

    # -----------------------------------------------------------------------
    # 3. 제목 및 URL 유효성 검사
    # -----------------------------------------------------------------------
    def is_valid_title(self, title: str) -> Tuple[bool, str]:
        """제목 유효성 검사 (결측, 초단문, 무의미 텍스트 판정)"""
        if not title:
            return False, "missing"

        stripped = title.strip()
        if len(stripped) == 0:
            return False, "missing"

        # 무의미한 플레이스홀더 체크
        if stripped.lower() in ["none", "null", "nan", "제목 없음", "no title", "untitled", "..."]:
            return False, "invalid_placeholder"

        # 한글, 영문, 숫자 개수 검사
        valid_chars = re.findall(r"[a-zA-Z0-9가-힣]", stripped)
        if len(valid_chars) < 4:
            return False, "too_short"

        # 전체 길이 검사 (최소 5자 이상)
        if len(stripped) < 5:
            return False, "too_short"

        return True, "valid"

    def is_valid_url(self, url: str) -> bool:
        """URL 유효성 검사"""
        if not url:
            return False
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return False
        if len(url) < 10:
            return False
        return True

    def normalize_title_for_dedup(self, title: str) -> str:
        """중복 판정을 위한 제목 정규화 키 생성"""
        # 특수문자, 괄호, 공백 제거 후 소문자화
        norm = re.sub(r"\[.*?\]|\(.*?\)|<.*?>", "", title)
        norm = re.sub(r"[^\w가-힣]", "", norm).lower()
        return norm

    def normalize_url_for_dedup(self, url: str) -> str:
        """중복 판정을 위한 URL 정규화 키 생성"""
        url = url.strip().rstrip("/")
        # URL 트래킹 파라미터 일부 정규화
        if "?" in url:
            base, qs = url.split("?", 1)
            # oc 파라미터 등 단일 쿼리 정규화
            qs_parts = [p for p in qs.split("&") if not p.startswith("oc=") and not p.startswith("utm_")]
            if qs_parts:
                url = f"{base}?{'&'.join(qs_parts)}"
            else:
                url = base
        return url.lower()

    # -----------------------------------------------------------------------
    # 4. 메인 정제 파이프라인
    # -----------------------------------------------------------------------
    def clean(self) -> List[Dict[str, Any]]:
        """전체 데이터 정제 및 중복/결측 제거 수행"""
        self.logger.info("=========================================================")
        self.logger.info(" [Cleaner] 데이터 정제 및 품질 검증 파이프라인 시작")
        self.logger.info(f" - 입력 원본: {self.raw_file}")
        self.logger.info("=========================================================")

        if not self.raw_file.exists():
            raise FileNotFoundError(f"원본 파일을 찾을 수 없습니다: {self.raw_file}")

        with open(self.raw_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            raw_rows = list(reader)

        self.stats["raw_count"] = len(raw_rows)
        self.logger.info(f">> 원본 데이터 {len(raw_rows)}행 로드 완료.")

        seen_urls = set()
        seen_title_keys = set()
        cleaned_rows = []

        for idx, row in enumerate(raw_rows, start=1):
            raw_title = row.get("title", "")
            raw_content = row.get("content", "")
            raw_summary = row.get("summary", "")
            raw_url = row.get("source_url", "")
            raw_date = row.get("date", "")
            collected_at = row.get("collected_at", "")

            # 1. HTML 태그 및 텍스트 정제
            title = self.clean_text(raw_title)
            content = self.clean_text(raw_content)
            summary = self.clean_text(raw_summary)

            if title != raw_title or content != raw_content or summary != raw_summary:
                self.stats["html_cleaned_count"] += 1

            # 2. 제목 유효성 검사 (결측 및 초단문 제거)
            is_valid, reason = self.is_valid_title(title)
            if not is_valid:
                if reason in ["missing", "invalid_placeholder"]:
                    self.stats["missing_title_dropped"] += 1
                    self.logger.debug(f"[제거: 빈 제목] 행 {idx}")
                else:
                    self.stats["short_title_dropped"] += 1
                    self.logger.debug(f"[제거: 초단문 제목] 행 {idx}: '{title}'")
                continue

            # 3. URL 유효성 검사
            if not self.is_valid_url(raw_url):
                self.stats["invalid_url_dropped"] += 1
                self.logger.debug(f"[제거: 무효 URL] 행 {idx}: '{raw_url}'")
                continue

            # 4. 날짜 정규화
            norm_date = self.normalize_date(raw_date, fallback_date=collected_at)
            if norm_date != raw_date:
                self.stats["date_normalized_count"] += 1

            # 5. 중복 검사 (URL 중복 및 제목 중복)
            url_key = self.normalize_url_for_dedup(raw_url)
            title_key = self.normalize_title_for_dedup(title)

            if url_key in seen_urls:
                self.stats["url_duplicate_dropped"] += 1
                self.logger.debug(f"[제거: URL 중복] 행 {idx}: {raw_url}")
                continue

            if title_key in seen_title_keys and len(title_key) > 8:
                self.stats["title_duplicate_dropped"] += 1
                self.logger.debug(f"[제거: 제목 중복] 행 {idx}: '{title}'")
                continue

            seen_urls.add(url_key)
            seen_title_keys.add(title_key)

            # content/summary 결측 보완
            if not summary and content:
                summary = content[:200]
            elif not content and summary:
                content = summary
            elif not content and not summary:
                content = title
                summary = title

            # 정제된 레코드 구성
            cleaned_row = dict(row)
            cleaned_row["title"] = title
            cleaned_row["content"] = content
            cleaned_row["summary"] = summary
            cleaned_row["date"] = norm_date
            cleaned_row["source_url"] = raw_url.strip()
            cleaned_row["source_name"] = self.clean_text(row.get("source_name", "Unknown"))
            cleaned_row["has_null"] = "false"
            cleaned_row["is_duplicate_seed"] = "false"
            cleaned_row["data_origin"] = row.get("data_origin", "live_crawled")

            cleaned_rows.append(cleaned_row)

        # 6. 고유 article_id 재부여 (CLN-0001 ...)
        for i, r in enumerate(cleaned_rows, start=1):
            r["article_id"] = f"CLN-{i:04d}"

        self.stats["cleaned_count"] = len(cleaned_rows)
        return cleaned_rows

    # -----------------------------------------------------------------------
    # 5. 저장 및 검증
    # -----------------------------------------------------------------------
    def save(self, cleaned_rows: List[Dict[str, Any]]) -> Path:
        """data/processed/cleaned_market_news.csv 저장 및 검증"""
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        fieldnames = [
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

        with open(self.output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in cleaned_rows:
                writer.writerow(r)

        self.logger.info(f"정제 데이터 저장 완료: {self.output_file} (총 {len(cleaned_rows)}행)")

        # project1 내부와 루트 양쪽 동기화
        try:
            alt_output = None
            if "project1" in str(self.base_dir):
                alt_output = self.base_dir.parent / "data" / "processed" / "cleaned_market_news.csv"
            else:
                alt_output = self.base_dir / "project1" / "data" / "processed" / "cleaned_market_news.csv"

            if alt_output:
                alt_output.parent.mkdir(parents=True, exist_ok=True)
                with open(alt_output, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    for r in cleaned_rows:
                        writer.writerow(r)
                self.logger.info(f"동기화 저장 완료: {alt_output}")
        except Exception as e:
            self.logger.warning(f"보조 디렉터리 동기화 생략: {e}")

        return self.output_file

    def verify(self, cleaned_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """무결성 검증 (중복 article_id/URL 없음, 빈 title 없음)"""
        article_ids = [r["article_id"] for r in cleaned_rows]
        urls = [r["source_url"] for r in cleaned_rows]
        titles = [r["title"] for r in cleaned_rows]

        duplicate_ids = len(article_ids) - len(set(article_ids))
        duplicate_urls = len(urls) - len(set(urls))
        empty_titles = sum(1 for t in titles if not t or len(t.strip()) == 0)

        passed = (duplicate_ids == 0) and (duplicate_urls == 0) and (empty_titles == 0) and (len(cleaned_rows) >= 200)

        result = {
            "passed": passed,
            "total_count": len(cleaned_rows),
            "duplicate_article_ids": duplicate_ids,
            "duplicate_urls": duplicate_urls,
            "empty_titles": empty_titles,
        }

        self.logger.info("--- [무결성 검증 결과] ---")
        self.logger.info(f" - 검증 통과 여부: {'PASS' if passed else 'FAIL'}")
        self.logger.info(f" - 최종 데이터 건수: {len(cleaned_rows)}건 (기준: 200건 이상)")
        self.logger.info(f" - 중복 article_id 수: {duplicate_ids}건")
        self.logger.info(f" - 중복 source_url 수: {duplicate_urls}건")
        self.logger.info(f" - 빈 title 수: {empty_titles}건")

        return result

    def run(self) -> Dict[str, Any]:
        """정제 파이프라인 전체 실행"""
        cleaned_rows = self.clean()
        output_path = self.save(cleaned_rows)
        verify_result = self.verify(cleaned_rows)

        total_duplicates_dropped = (
            self.stats["exact_duplicate_dropped"]
            + self.stats["url_duplicate_dropped"]
            + self.stats["title_duplicate_dropped"]
        )
        total_invalid_dropped = (
            self.stats["missing_title_dropped"]
            + self.stats["short_title_dropped"]
            + self.stats["invalid_url_dropped"]
        )

        return {
            "output_file": str(output_path),
            "raw_count": self.stats["raw_count"],
            "cleaned_count": self.stats["cleaned_count"],
            "duplicates_removed": total_duplicates_dropped,
            "invalid_missing_removed": total_invalid_dropped,
            "stats_detail": self.stats,
            "verification": verify_result
        }


# ---------------------------------------------------------------------------
# CLI 엔트리포인트
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cleaner = MarketNewsCleaner()
    res = cleaner.run()

    print("\n" + "=" * 60)
    print(" [DATA CLEANING EXECUTION SUMMARY REPORT]")
    print("=" * 60)
    print(f"[*] 원본 건수 (Raw Count)       : {res['raw_count']}건")
    print(f"[*] 최종 건수 (Cleaned Count)   : {res['cleaned_count']}건")
    print(f"[*] 중복 제거 수 (Duplicates)   : {res['duplicates_removed']}건")
    print(f"    - URL 중복 제거             : {res['stats_detail']['url_duplicate_dropped']}건")
    print(f"    - 제목 유사 중복 제거       : {res['stats_detail']['title_duplicate_dropped']}건")
    print(f"[*] 결측/무효 제거 수 (Invalid) : {res['invalid_missing_removed']}건")
    print(f"    - 빈 제목 제거              : {res['stats_detail']['missing_title_dropped']}건")
    print(f"    - 초단문/무효 제목 제거     : {res['stats_detail']['short_title_dropped']}건")
    print(f"    - 무효 URL 제거             : {res['stats_detail']['invalid_url_dropped']}건")
    print(f"[*] 텍스트 정제(HTML 제거 등)   : {res['stats_detail']['html_cleaned_count']}건")
    print(f"[*] 날짜 정규화 수행            : {res['stats_detail']['date_normalized_count']}건")
    print("-" * 60)
    print(f"[*] 저장 위치: {res['output_file']}")
    print(f"[*] 무결성 검증 (Verification)  : {'PASS (성공)' if res['verification']['passed'] else 'FAIL (실패)'}")
    print(f"    - 중복 article_id           : {res['verification']['duplicate_article_ids']}건")
    print(f"    - 중복 source_url           : {res['verification']['duplicate_urls']}건")
    print(f"    - 빈 title                  : {res['verification']['empty_titles']}건")
    print(f"    - 최소 200건 기준 달성      : {'달성' if res['cleaned_count'] >= 200 else '미달'}")
    print("=" * 60)
