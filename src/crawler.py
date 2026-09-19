"""
Market & Competitor Intelligence Crawler (시장·경쟁사·정책 정보 수집기)

- 대상 기업: NovaFactory AI (config/company_profile.yaml)
- 수집 출처: 공개 RSS, 공개 API, 공개 HTML 웹페이지 (source_plan.md 기반)
- 저장 위치: data/raw/crawled_market_news.csv
- 복원력: Source 개별 실패 시 전체 파이프라인 유지, 200건 미만 시 대체 Source 및 Fallback 데이터 결합
"""

import os
import sys
import csv
import re
import html
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple
from urllib.parse import quote
import xml.etree.ElementTree as ET

import yaml
import requests
from bs4 import BeautifulSoup

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
    log_file = log_dir / "crawler.log"

    logger = logging.getLogger("MarketCrawler")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # 콘솔 핸들러 (UTF-8 인코딩 보장)
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
# MarketNewsCrawler 클래스
# ---------------------------------------------------------------------------
class MarketNewsCrawler:
    def __init__(self, base_dir: Path = None):
        if base_dir is None:
            # src/crawler.py 기준 상위 디렉터리 탐색
            current_file = Path(__file__).resolve()
            if (current_file.parent.parent / "config" / "company_profile.yaml").exists():
                self.base_dir = current_file.parent.parent
            elif (current_file.parent.parent / "project1" / "config" / "company_profile.yaml").exists():
                self.base_dir = current_file.parent.parent / "project1"
            else:
                self.base_dir = Path.cwd()
        else:
            self.base_dir = base_dir

        self.config_path = self.base_dir / "config" / "company_profile.yaml"
        self.raw_data_dir = self.base_dir / "data" / "raw"
        self.fallback_file = self.base_dir / "data" / "fallback" / "fallback_market_news.csv"
        self.log_dir = self.base_dir / "logs"

        self.logger = setup_logging(self.log_dir)
        self.config = self._load_config()

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        self.collected_items: List[Dict[str, Any]] = []
        self.seen_urls: set = set()
        self.seen_titles: set = set()
        self.failed_sources: List[Dict[str, str]] = []

    def _load_config(self) -> Dict[str, Any]:
        """company_profile.yaml 로드"""
        if not self.config_path.exists():
            self.logger.warning(f"설정 파일 미발견: {self.config_path}. 기본 설정 사용.")
            return {
                "company_name": "NovaFactory AI",
                "competitors": ["VisionForge", "InspectAI", "FactoryMind", "QualiBot"],
                "interest_keywords": ["AI", "스마트팩토리", "품질검사", "자동화", "클라우드", "제조 AX", "디지털 전환", "머신비전"],
                "funding_keywords": ["창업지원", "AI 바우처", "스마트공장", "R&D", "사업화 자금", "중소기업 지원"]
            }
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            self.logger.info(f"기업 프로필 로드 완료: {cfg.get('company_name', 'Unknown')}")
            return cfg

    def _clean_html(self, raw_html: str) -> str:
        """HTML 태그 제거 및 텍스트 정제"""
        if not raw_html:
            return ""
        clean = re.sub(r"<[^>]+>", " ", raw_html)
        clean = html.unescape(clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _format_date(self, raw_date_str: str) -> str:
        """날짜 문자열을 YYYY-MM-DD 형식으로 변환"""
        if not raw_date_str:
            return datetime.now().strftime("%Y-%m-%d")
        try:
            # RFC 822 format (e.g., 'Wed, 18 Sep 2026 09:00:00 GMT')
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(raw_date_str)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        # ISO format or YYYY-MM-DD pattern
        match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", raw_date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}-{int(m):02d}-{int(d):02d}"

        return datetime.now().strftime("%Y-%m-%d")

    def _add_item(self, item: Dict[str, Any]) -> bool:
        """중복 검사 후 아이템 추가"""
        url = item.get("source_url", "").strip()
        title = item.get("title", "").strip()

        if not title or len(title) < 5:
            return False

        if url and url in self.seen_urls:
            return False
        if title in self.seen_titles:
            return False

        if url:
            self.seen_urls.add(url)
        self.seen_titles.add(title)
        self.collected_items.append(item)
        return True

    # -----------------------------------------------------------------------
    # 1. Google News RSS 수집기 (1순위: 공개 RSS)
    # -----------------------------------------------------------------------
    def collect_google_news_rss(self) -> int:
        """Google News RSS 키워드 검색 수집"""
        self.logger.info("=== [Source 1] Google News RSS 수집 시작 ===")

        # 카테고리별 쿼리 정의
        query_specs = [
            {
                "category": "market",
                "query": '제조 AI 시장 OR 스마트팩토리 도입',
                "desc": "스마트팩토리 및 제조 AI 시장 트렌드"
            },
            {
                "category": "competitor",
                "query": 'AI 비전 검사 스타트업 OR 머신비전 솔루션 기업',
                "desc": "머신비전 및 비전 검사 경쟁 생태계"
            },
            {
                "category": "policy",
                "query": '스마트제조 2.0 OR 제조업 AX 정책 OR 중소기업 디지털 전환',
                "desc": "제조업 AX 및 디지털 전환 정책"
            },
            {
                "category": "funding",
                "query": '"AI 바우처" OR "스마트공장 구축" OR "중소기업 R&D 지원"',
                "desc": "정부 지원사업 및 펀딩"
            },
            {
                "category": "technology",
                "query": '"엣지 AI" OR "머신비전 품질검사" OR "딥러닝 외관검사"',
                "desc": "산업용 엣지 AI 및 비전 검사 기술"
            }
        ]

        # 경쟁사 명시 쿼리 추가
        competitors = self.config.get("competitors", [])
        if competitors:
            comp_q = " OR ".join([f'"{c}"' for c in competitors])
            query_specs.append({
                "category": "competitor",
                "query": comp_q,
                "desc": f"지정 경쟁사 ({', '.join(competitors)})"
            })

        count_before = len(self.collected_items)

        for spec in query_specs:
            cat = spec["category"]
            q = spec["query"]
            encoded_q = quote(q)
            rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=ko&gl=KR&ceid=KR:ko"

            try:
                res = requests.get(rss_url, headers=self.headers, timeout=10)
                if res.status_code != 200:
                    self.logger.warning(f"Google News RSS HTTP {res.status_code} ({spec['desc']})")
                    self.failed_sources.append({"source": f"Google News RSS: {spec['desc']}", "error": f"HTTP {res.status_code}"})
                    continue

                root = ET.fromstring(res.content)
                items = root.findall(".//item")
                added_for_query = 0

                for it in items:
                    raw_title = it.find("title").text if it.find("title") is not None else ""
                    raw_link = it.find("link").text if it.find("link") is not None else ""
                    raw_date = it.find("pubDate").text if it.find("pubDate") is not None else ""
                    raw_desc = it.find("description").text if it.find("description") is not None else ""
                    source_elem = it.find("source")
                    source_name = source_elem.text if source_elem is not None else "Google News"

                    # 언론사명이 제목 끝에 붙어 있는 경우 분리 ('기사 제목 - 언론사')
                    clean_title = raw_title
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        clean_title = parts[0].strip()
                        if source_name == "Google News" and len(parts) > 1:
                            source_name = parts[1].strip()

                    clean_desc = self._clean_html(raw_desc)
                    formatted_date = self._format_date(raw_date)

                    # 키워드 매칭 태그
                    matched_kws = [kw for kw in self.config.get("interest_keywords", []) + self.config.get("funding_keywords", []) if kw.lower() in clean_title.lower() or kw.lower() in clean_desc.lower()]
                    matched_comp = [c for c in competitors if c.lower() in clean_title.lower() or c.lower() in clean_desc.lower()]

                    record = {
                        "article_id": "",
                        "category": cat,
                        "title": clean_title,
                        "date": formatted_date,
                        "content": clean_desc,
                        "summary": clean_desc[:200] if len(clean_desc) > 200 else clean_desc,
                        "source_url": raw_link,
                        "source_name": source_name,
                        "company_tag": matched_comp[0] if matched_comp else "",
                        "keywords": "|".join(matched_kws[:4]),
                        "collected_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                        "has_null": "false",
                        "is_duplicate_seed": "false",
                        "data_origin": "live_crawled"
                    }

                    if self._add_item(record):
                        added_for_query += 1

                self.logger.info(f"Google News [{spec['desc']}]: {added_for_query}건 수집 성공 (총 피드 {len(items)}건 중)")

            except Exception as e:
                self.logger.error(f"Google News RSS 예외 ({spec['desc']}): {e}")
                self.failed_sources.append({"source": f"Google News RSS ({spec['desc']})", "error": str(e)})

        total_google = len(self.collected_items) - count_before
        self.logger.info(f"==> Google News RSS 총 수집: {total_google}건")
        return total_google

    # -----------------------------------------------------------------------
    # 2. 전자신문(ETNews) RSS 수집기 (1순위: 공개 RSS)
    # -----------------------------------------------------------------------
    def collect_etnews_rss(self) -> int:
        """전자신문 소프트웨어/산업 IT RSS 피드 수집"""
        self.logger.info("=== [Source 2] 전자신문(ETNews) RSS 수집 시작 ===")
        url = "https://rss.etnews.com/Section902.xml"
        count_before = len(self.collected_items)

        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code != 200:
                self.logger.warning(f"ETNews RSS HTTP {res.status_code}")
                self.failed_sources.append({"source": "ETNews RSS", "error": f"HTTP {res.status_code}"})
                return 0

            root = ET.fromstring(res.content)
            items = root.findall(".//item")
            added = 0

            for it in items:
                title = it.find("title").text if it.find("title") is not None else ""
                link = it.find("link").text if it.find("link") is not None else ""
                pub_date = it.find("pubDate").text if it.find("pubDate") is not None else ""
                desc = it.find("description").text if it.find("description") is not None else ""

                clean_title = self._clean_html(title)
                clean_desc = self._clean_html(desc)
                formatted_date = self._format_date(pub_date)

                # 카테고리 판별
                cat = "technology"
                if any(w in clean_title for w in ["정책", "정부", "지원", "예산", "법", "규제"]):
                    cat = "policy"
                elif any(w in clean_title for w in ["시장", "매출", "투자", "성장", "수출", "전망"]):
                    cat = "market"

                record = {
                    "article_id": "",
                    "category": cat,
                    "title": clean_title,
                    "date": formatted_date,
                    "content": clean_desc,
                    "summary": clean_desc[:200] if len(clean_desc) > 200 else clean_desc,
                    "source_url": link,
                    "source_name": "전자신문(ETNews)",
                    "company_tag": "",
                    "keywords": "IT|소프트웨어|산업DX",
                    "collected_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                    "has_null": "false",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawled"
                }

                if self._add_item(record):
                    added += 1

            self.logger.info(f"==> 전자신문(ETNews) 수집: {added}건")
            return added

        except Exception as e:
            self.logger.error(f"ETNews RSS 수집 실패: {e}")
            self.failed_sources.append({"source": "ETNews RSS", "error": str(e)})
            return 0

    # -----------------------------------------------------------------------
    # 3. ArXiv Open Search API 수집기 (3순위: 공개 API)
    # -----------------------------------------------------------------------
    def collect_arxiv_api(self, max_results: int = 50) -> int:
        """ArXiv 오픈 API를 통한 산업용 비전/결함 검사 논문 기술동향 수집"""
        self.logger.info("=== [Source 3] ArXiv Open API 수집 시작 ===")
        # defect inspection AND machine vision
        query = "all:defect+inspection+AND+all:vision"
        url = f"http://export.arxiv.org/api/query?search_query={query}&start=0&max_results={max_results}"
        count_before = len(self.collected_items)

        try:
            res = requests.get(url, headers=self.headers, timeout=12)
            if res.status_code != 200:
                self.logger.warning(f"ArXiv API HTTP {res.status_code}")
                self.failed_sources.append({"source": "ArXiv Open API", "error": f"HTTP {res.status_code}"})
                return 0

            root = ET.fromstring(res.content)
            entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            added = 0

            for entry in entries:
                title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
                summary_elem = entry.find("{http://www.w3.org/2005/Atom}summary")
                published_elem = entry.find("{http://www.w3.org/2005/Atom}published")
                id_elem = entry.find("{http://www.w3.org/2005/Atom}id")

                title = title_elem.text.strip().replace("\n", " ") if title_elem is not None else ""
                summary = summary_elem.text.strip().replace("\n", " ") if summary_elem is not None else ""
                link = id_elem.text.strip() if id_elem is not None else ""
                pub_date = published_elem.text.strip() if published_elem is not None else ""

                formatted_date = self._format_date(pub_date)

                record = {
                    "article_id": "",
                    "category": "technology",
                    "title": f"[연구동향] {title}",
                    "date": formatted_date,
                    "content": summary,
                    "summary": summary[:250] if len(summary) > 250 else summary,
                    "source_url": link,
                    "source_name": "ArXiv Computer Vision",
                    "company_tag": "",
                    "keywords": "AI 비전|불량검사|딥러닝|머신비전",
                    "collected_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                    "has_null": "false",
                    "is_duplicate_seed": "false",
                    "data_origin": "live_crawled"
                }

                if self._add_item(record):
                    added += 1

            self.logger.info(f"==> ArXiv API 수집: {added}건")
            return added

        except Exception as e:
            self.logger.error(f"ArXiv API 수집 실패: {e}")
            self.failed_sources.append({"source": "ArXiv API", "error": str(e)})
            return 0

    # -----------------------------------------------------------------------
    # 4. 기업마당 (Bizinfo) 지원사업 공고 수집기 (2순위: requests)
    # -----------------------------------------------------------------------
    def collect_bizinfo(self, pages: int = 3) -> int:
        """기업마당(Bizinfo) 중소벤처기업부 지원사업 공고 스크래핑"""
        self.logger.info("=== [Source 4] 기업마당(Bizinfo) 지원사업 공고 수집 시작 ===")
        base_url = "https://www.bizinfo.go.kr"
        added = 0

        for page in range(1, pages + 1):
            url = f"https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/list.do?cpage={page}"
            try:
                res = requests.get(url, headers=self.headers, timeout=10)
                if res.status_code != 200:
                    self.logger.warning(f"Bizinfo Page {page} HTTP {res.status_code}")
                    self.failed_sources.append({"source": f"Bizinfo Page {page}", "error": f"HTTP {res.status_code}"})
                    continue

                soup = BeautifulSoup(res.text, "html.parser")
                links = soup.find_all("a")

                page_added = 0
                for a in links:
                    href = a.get("href", "")
                    title = a.get_text(strip=True)
                    if not title or len(title) < 10:
                        continue

                    # 지원사업 상세 링크 식별
                    if "selectSIIA200Detail.do" in href or ("view.do" in href and any(k in title for k in ["지원", "사업", "모집", "공고", "자금"])):
                        full_url = href if href.startswith("http") else base_url + href

                        record = {
                            "article_id": "",
                            "category": "funding",
                            "title": title,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "content": f"중소벤처기업부 기업마당 지원사업 공고: {title}",
                            "summary": f"{title} - 중소기업 지원 및 기술 사업화 공고",
                            "source_url": full_url,
                            "source_name": "중소벤처기업부 기업마당",
                            "company_tag": "",
                            "keywords": "중소기업 지원|사업화 자금|R&D",
                            "collected_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                            "has_null": "false",
                            "is_duplicate_seed": "false",
                            "data_origin": "live_crawled"
                        }

                        if self._add_item(record):
                            page_added += 1
                            added += 1

                self.logger.info(f"Bizinfo {page}페이지: {page_added}건 수집")

            except Exception as e:
                self.logger.error(f"Bizinfo {page}페이지 수집 실패: {e}")
                self.failed_sources.append({"source": f"Bizinfo Page {page}", "error": str(e)})

        self.logger.info(f"==> 기업마당 총 수집: {added}건")
        return added

    # -----------------------------------------------------------------------
    # 5. K-Startup 사업공고 수집기 (2순위: requests)
    # -----------------------------------------------------------------------
    def collect_kstartup(self) -> int:
        """K-Startup 창업진흥원 사업공고 수집"""
        self.logger.info("=== [Source 5] K-Startup 사업공고 수집 시작 ===")
        url = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
        base_domain = "https://www.k-startup.go.kr"
        added = 0

        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code != 200:
                self.logger.warning(f"K-Startup HTTP {res.status_code}")
                self.failed_sources.append({"source": "K-Startup", "error": f"HTTP {res.status_code}"})
                return 0

            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select(".notice_list li, .list_table tbody tr, .board_list tbody tr")

            if not items:
                # 링크 직접 검색
                for a in soup.find_all("a"):
                    txt = a.get_text(strip=True)
                    href = a.get("href", "")
                    if len(txt) > 12 and any(k in txt for k in ["공고", "모집", "지원", "사업", "스타트업", "패키지"]):
                        full_url = href if href.startswith("http") else base_domain + href
                        record = {
                            "article_id": "",
                            "category": "funding",
                            "title": txt,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "content": f"K-Startup 창업진흥원 지원사업 공고: {txt}",
                            "summary": f"{txt} - 창업도약 및 AI 스타트업 펀딩 공고",
                            "source_url": full_url,
                            "source_name": "K-Startup 창업진흥원",
                            "company_tag": "",
                            "keywords": "창업지원|AI 바우처|사업화 자금",
                            "collected_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                            "has_null": "false",
                            "is_duplicate_seed": "false",
                            "data_origin": "live_crawled"
                        }
                        if self._add_item(record):
                            added += 1
            else:
                for row in items:
                    a_tag = row.find("a")
                    if not a_tag:
                        continue
                    title = a_tag.get_text(strip=True)
                    href = a_tag.get("href", "")
                    full_url = href if href.startswith("http") else base_domain + href

                    record = {
                        "article_id": "",
                        "category": "funding",
                        "title": title,
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "content": f"K-Startup 창업진흥원 사업공고: {title}",
                        "summary": f"{title} - 창업진흥원 지원사업",
                        "source_url": full_url,
                        "source_name": "K-Startup 창업진흥원",
                        "company_tag": "",
                        "keywords": "창업지원|사업화 자금",
                        "collected_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                        "has_null": "false",
                        "is_duplicate_seed": "false",
                        "data_origin": "live_crawled"
                    }
                    if self._add_item(record):
                        added += 1

            self.logger.info(f"==> K-Startup 수집: {added}건")
            return added

        except Exception as e:
            self.logger.error(f"K-Startup 수집 실패: {e}")
            self.failed_sources.append({"source": "K-Startup", "error": str(e)})
            return 0

    # -----------------------------------------------------------------------
    # 6. 대체 Source 수집기 (200건 미만 시 발동)
    # -----------------------------------------------------------------------
    def collect_backup_sources(self) -> int:
        """200건 미만 시 발동하는 확장 키워드 및 추가 공개 소스"""
        self.logger.info("=== [Backup Sources] 200건 보강을 위한 대체 Source 수집 발동 ===")
        added = 0

        extra_queries = [
            ("market", '"산업용 AI" OR "머신비전 시장" OR "제조 소프트웨어"'),
            ("technology", '"품질 불량" OR "외관 결함" OR "비전 센서 검사"'),
            ("policy", '"디지털제조혁신" OR "스마트팩토리 보급" OR "산업 데이터"'),
            ("funding", '"스마트제조혁신 R&D" OR "제조 바우처" OR "디지털 전환 지원"')
        ]

        for cat, q in extra_queries:
            rss_url = f"https://news.google.com/rss/search?q={quote(q)}&hl=ko&gl=KR&ceid=KR:ko"
            try:
                res = requests.get(rss_url, headers=self.headers, timeout=10)
                if res.status_code == 200:
                    root = ET.fromstring(res.content)
                    items = root.findall(".//item")
                    for it in items:
                        t = it.find("title").text if it.find("title") is not None else ""
                        l = it.find("link").text if it.find("link") is not None else ""
                        d = it.find("pubDate").text if it.find("pubDate") is not None else ""
                        desc = it.find("description").text if it.find("description") is not None else ""

                        clean_t = self._clean_html(t)
                        clean_d = self._clean_html(desc)

                        record = {
                            "article_id": "",
                            "category": cat,
                            "title": clean_t,
                            "date": self._format_date(d),
                            "content": clean_d,
                            "summary": clean_d[:200] if len(clean_d) > 200 else clean_d,
                            "source_url": l,
                            "source_name": "Google News (Backup)",
                            "company_tag": "",
                            "keywords": "스마트팩토리|제조AI",
                            "collected_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                            "has_null": "false",
                            "is_duplicate_seed": "false",
                            "data_origin": "live_crawled"
                        }
                        if self._add_item(record):
                            added += 1
            except Exception as e:
                self.logger.warning(f"대체 Source 쿼리 실패 ({q}): {e}")

        self.logger.info(f"==> 대체 Source 수집 완료: {added}건 추가")
        return added

    # -----------------------------------------------------------------------
    # 7. Fallback 데이터 결합기
    # -----------------------------------------------------------------------
    def merge_fallback_data(self, target_count: int = 200) -> int:
        """200건 미달 시 fallback_market_news.csv 데이터 병합"""
        current_count = len(self.collected_items)
        needed = target_count - current_count
        if needed <= 0:
            self.logger.info(f"현재 라이브 수집 건수({current_count}건)가 목표({target_count}건)를 이미 달성하여 Fallback 병합 불필요.")
            return 0

        self.logger.warning(f"현재 {current_count}건으로 목표 {target_count}건에 미달 ({needed}건 필요). Fallback 데이터를 결합합니다.")

        if not self.fallback_file.exists():
            self.logger.error(f"Fallback 파일 미발견: {self.fallback_file}")
            return 0

        added_fallback = 0
        try:
            with open(self.fallback_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 필수 컬럼 검사 및 data_origin 보장
                    title = row.get("title", "").strip()
                    url = row.get("source_url", "").strip()

                    if title in self.seen_titles or (url and url in self.seen_urls):
                        continue

                    # Fallback 표시
                    row["data_origin"] = "synthetic_fallback"
                    row["collected_at"] = datetime.now(timezone(timedelta(hours=9))).isoformat()

                    self.collected_items.append(row)
                    self.seen_titles.add(title)
                    if url:
                        self.seen_urls.add(url)
                    added_fallback += 1

                    if len(self.collected_items) >= target_count:
                        break

            self.logger.info(f"==> Fallback 데이터 {added_fallback}건 성공적으로 병합 완료! (총 {len(self.collected_items)}건)")
            return added_fallback

        except Exception as e:
            self.logger.error(f"Fallback 데이터 병합 실패: {e}")
            return 0

    # -----------------------------------------------------------------------
    # 8. CSV 저장 및 번호 매기기
    # -----------------------------------------------------------------------
    def save_to_csv(self) -> Path:
        """수집 데이터를 data/raw/crawled_market_news.csv로 저장"""
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.raw_data_dir / "crawled_market_news.csv"

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

        # article_id 부여
        for idx, item in enumerate(self.collected_items, start=1):
            if not item.get("article_id"):
                prefix = "LIVE" if item.get("data_origin") == "live_crawled" else "FB"
                item["article_id"] = f"{prefix}-{idx:04d}"

        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for it in self.collected_items:
                writer.writerow(it)

        self.logger.info(f"최종 CSV 저장 완료: {output_file} (총 {len(self.collected_items)}행)")
        return output_file

    # -----------------------------------------------------------------------
    # 메인 실행 파이프라인
    # -----------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        """전체 수집 프로세스 실행 및 통계 리턴"""
        start_time = datetime.now()
        self.logger.info("=========================================================")
        self.logger.info(" [Crawler] 시장·경쟁사·정책 정보 수집 파이프라인 시작")
        self.logger.info("=========================================================")

        # 1. 1순위: 공개 RSS (Google News, ETNews)
        self.collect_google_news_rss()
        self.collect_etnews_rss()

        # 2. 3순위: 공개 API (ArXiv)
        self.collect_arxiv_api(max_results=50)

        # 3. 2순위: requests 정적 웹 (기업마당, K-Startup)
        self.collect_bizinfo(pages=3)
        self.collect_kstartup()

        live_collected_count = len(self.collected_items)
        self.logger.info(f">> 1차 수집 완료: 라이브 데이터 {live_collected_count}건")

        # 4. 200건 미만 체크 & 대체 Source 시도
        backup_count = 0
        if len(self.collected_items) < 200:
            self.logger.info(f"수집 건수({len(self.collected_items)}건)가 200건 미만이므로 대체 Source 시도")
            backup_count = self.collect_backup_sources()

        live_total_count = len(self.collected_items)

        # 5. 그래도 200건 미만이면 Fallback 결합
        fallback_count = 0
        if len(self.collected_items) < 200:
            fallback_count = self.merge_fallback_data(target_count=200)

        # 6. CSV 저장
        output_file = self.save_to_csv()

        elapsed = (datetime.now() - start_time).total_seconds()
        self.logger.info("=========================================================")
        self.logger.info(f" [Crawler 완료] 총 소요시간: {elapsed:.2f}초")
        self.logger.info(f" - 라이브 수집 건수: {live_total_count}건")
        self.logger.info(f" - Fallback 결합 건수: {fallback_count}건")
        self.logger.info(f" - 최종 저장 건수: {len(self.collected_items)}건")
        self.logger.info(f" - 실패 Source 수: {len(self.failed_sources)}개")
        self.logger.info("=========================================================")

        # 카테고리별 통계
        cat_counts = {}
        for it in self.collected_items:
            c = it.get("category", "unknown")
            cat_counts[c] = cat_counts.get(c, 0) + 1

        return {
            "output_file": str(output_file),
            "total_count": len(self.collected_items),
            "live_count": live_total_count,
            "fallback_count": fallback_count,
            "failed_sources": self.failed_sources,
            "category_distribution": cat_counts,
            "elapsed_seconds": elapsed
        }


# ---------------------------------------------------------------------------
# CLI 엔트리포인트
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    crawler = MarketNewsCrawler()
    result = crawler.run()

    print("\n" + "=" * 60)
    print(" [CRAWLER EXECUTION SUMMARY REPORT]")
    print("=" * 60)
    print(f"[*] 저장 파일: {result['output_file']}")
    print(f"[*] 총 저장 데이터: {result['total_count']}건 (최소 200건 요구 만족: {'PASS' if result['total_count'] >= 200 else 'FAIL'})")
    print(f"[*] 실제 라이브 수집: {result['live_count']}건")
    print(f"[*] Fallback 데이터: {result['fallback_count']}건")
    print(f"[*] 카테고리별 분포:")
    for cat, cnt in result["category_distribution"].items():
        print(f"    - {cat}: {cnt}건")
    print(f"[*] 실패 Source: {len(result['failed_sources'])}개")
    for f in result["failed_sources"]:
        print(f"    - {f['source']}: {f['error']}")
    print("=" * 60)
