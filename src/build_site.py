"""
Market & Competitor Intelligence Static Site Builder (정적 웹 대시보드 빌더)

- 입력:
  - data/processed/recommended_market_news.csv (상위 30건)
  - data/processed/cleaned_market_news.csv (전체 572건)
  - config/company_profile.yaml
- 출력:
  - docs/index.html (GitHub Pages용 정적 대시보드)
  - docs/report.json (머신 리더블 JSON 리포트)
"""

import os
import sys
import csv
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple

import yaml

# Windows 콘솔 출력 인코딩 안전화
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "build_site.log"

    logger = logging.getLogger("SiteBuilder")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


class SiteBuilder:
    def __init__(self, base_dir: Path = None):
        if base_dir is None:
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
        self.recommended_file = self.base_dir / "data" / "processed" / "recommended_market_news.csv"
        self.cleaned_file = self.base_dir / "data" / "processed" / "cleaned_market_news.csv"
        self.docs_dir = self.base_dir / "docs"
        self.log_dir = self.base_dir / "logs"

        self.logger = setup_logging(self.log_dir)
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {
                "company_name": "NovaFactory AI",
                "business_area": "제조업 AI 비전 품질검사",
                "products": ["비전 기반 불량 탐지 SaaS", "제조 품질 리포트 자동화", "엣지 AI 품질 분석 솔루션"],
                "target_market": ["중소·중견 제조기업", "스마트팩토리 구축 기업", "반도체/전자부품 외관 검사 공정"],
                "competitors": ["VisionForge", "InspectAI", "FactoryMind", "QualiBot"]
            }
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def load_data(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if not self.recommended_file.exists():
            raise FileNotFoundError(f"추천 파일이 없습니다: {self.recommended_file}. 먼저 recommender.py를 실행하세요.")

        with open(self.recommended_file, "r", encoding="utf-8") as f:
            recommended = list(csv.DictReader(f))

        cleaned = []
        if self.cleaned_file.exists():
            with open(self.cleaned_file, "r", encoding="utf-8") as f:
                cleaned = list(csv.DictReader(f))

        return recommended, cleaned

    def generate_report_json(self, recommended: List[Dict[str, Any]], cleaned: List[Dict[str, Any]], llm_used: bool = False) -> Path:
        """docs/report.json 생성"""
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        report_file = self.docs_dir / "report.json"

        # 카테고리 통계
        all_cat_counts = {}
        for r in cleaned:
            c = r.get("category", "unknown")
            all_cat_counts[c] = all_cat_counts.get(c, 0) + 1

        top30_cat_counts = {}
        for r in recommended:
            c = r.get("category", "unknown")
            top30_cat_counts[c] = top30_cat_counts.get(c, 0) + 1

        top_10 = recommended[:10]

        report_data = {
            "metadata": {
                "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                "company_name": self.config.get("company_name", "NovaFactory AI"),
                "business_area": self.config.get("business_area", "제조업 AI 비전 품질검사"),
                "total_analyzed_count": len(cleaned),
                "recommended_count": len(recommended),
                "llm_used": llm_used,
                "engine_type": "Gemini 2.5 Flash LLM Ensemble" if llm_used else "Multi-dimensional Rule-based Intelligence Engine"
            },
            "statistics": {
                "total_category_distribution": all_cat_counts,
                "top30_category_distribution": top30_cat_counts,
                "highest_score": float(recommended[0]["total_score"]) if recommended else 0.0,
                "average_top10_score": round(sum(float(x["total_score"]) for x in top_10) / len(top_10), 1) if top_10 else 0.0
            },
            "top_10": top_10,
            "recommended_30": recommended
        }

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"docs/report.json 저장 완료: {report_file}")

        try:
            alt = self.base_dir.parent / "docs" / "report.json" if "project1" in str(self.base_dir) else self.base_dir / "project1" / "docs" / "report.json"
            alt.parent.mkdir(parents=True, exist_ok=True)
            with open(alt, "w", encoding="utf-8") as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return report_file

    def generate_html_dashboard(self, recommended: List[Dict[str, Any]], cleaned: List[Dict[str, Any]], llm_used: bool = False) -> Path:
        """docs/index.html 정적 대시보드 생성"""
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        html_file = self.docs_dir / "index.html"

        company_name = self.config.get("company_name", "NovaFactory AI")
        business_area = self.config.get("business_area", "제조업 AI 비전 품질검사")
        total_analyzed = len(cleaned)
        recommended_count = len(recommended)
        highest_score = recommended[0]["total_score"] if recommended else "0"
        engine_label = "Gemini 2.5 Flash + Rule Ensemble" if llm_used else "Rule-based Intelligence Engine"

        top30_cat_counts = {}
        for r in recommended:
            c = r.get("category", "unknown")
            top30_cat_counts[c] = top30_cat_counts.get(c, 0) + 1

        top_10 = recommended[:10]

        cat_meta = {
            "competitor": {"label": "경쟁사 동향", "bg": "bg-rose-500", "text": "text-rose-600", "border": "border-rose-200", "badge": "bg-rose-100 text-rose-800"},
            "technology": {"label": "기술 동향", "bg": "bg-blue-500", "text": "text-blue-600", "border": "border-blue-200", "badge": "bg-blue-100 text-blue-800"},
            "market": {"label": "시장 트렌드", "bg": "bg-emerald-500", "text": "text-emerald-600", "border": "border-emerald-200", "badge": "bg-emerald-100 text-emerald-800"},
            "funding": {"label": "정부지원/펀딩", "bg": "bg-amber-500", "text": "text-amber-600", "border": "border-amber-200", "badge": "bg-amber-100 text-amber-800"},
            "policy": {"label": "정책/규제", "bg": "bg-purple-500", "text": "text-purple-600", "border": "border-purple-200", "badge": "bg-purple-100 text-purple-800"}
        }

        top10_html = ""
        for item in top_10:
            rank = int(item.get("rank", 1))
            score = float(item.get("total_score", 0))
            cat = item.get("category", "market")
            cm = cat_meta.get(cat, {"label": cat, "badge": "bg-slate-100 text-slate-800", "text": "text-slate-600", "bg": "bg-slate-500"})

            if rank == 1:
                rank_badge = "bg-amber-500 text-white font-extrabold ring-4 ring-amber-100 shadow-md"
                card_border = "border-amber-300 ring-1 ring-amber-200"
            elif rank == 2:
                rank_badge = "bg-slate-400 text-white font-bold ring-4 ring-slate-100 shadow"
                card_border = "border-slate-300"
            elif rank == 3:
                rank_badge = "bg-amber-700 text-white font-bold ring-4 ring-amber-50 shadow"
                card_border = "border-amber-200"
            else:
                rank_badge = "bg-indigo-50 text-indigo-700 font-semibold"
                card_border = "border-slate-200 hover:border-indigo-200"

            top10_html += f"""
            <div class="bg-white rounded-2xl p-6 border {card_border} shadow-sm hover:shadow-lg transition-all duration-300 flex flex-col justify-between">
                <div>
                    <div class="flex items-center justify-between mb-3">
                        <div class="flex items-center gap-2">
                            <span class="w-8 h-8 rounded-xl flex items-center justify-center text-sm {rank_badge}">{rank:02d}</span>
                            <span class="text-xs px-2.5 py-1 rounded-full font-semibold {cm['badge']}">{cm['label']}</span>
                        </div>
                        <div class="flex items-center gap-1.5">
                            <span class="text-xs text-slate-400 font-medium">적합도</span>
                            <span class="text-base font-extrabold {cm['text']}">{score:.1f}점</span>
                        </div>
                    </div>

                    <div class="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden mb-4">
                        <div class="{cm['bg']} h-full rounded-full" style="width: {min(100, score)}%"></div>
                    </div>

                    <h3 class="text-base font-bold text-slate-900 leading-snug mb-3 hover:text-indigo-600 transition-colors line-clamp-2">
                        {item.get('title')}
                    </h3>

                    <div class="p-3.5 bg-slate-50 rounded-xl border border-slate-100 text-xs text-slate-700 leading-relaxed mb-4">
                        <div class="font-semibold text-slate-900 mb-1 flex items-center gap-1.5">
                            <svg class="w-3.5 h-3.5 text-indigo-500" fill="currentColor" viewBox="0 0 20 20"><path d="M10 2a8 8 0 100 16 8 8 0 000-16zm1 11H9v-2h2v2zm0-4H9V5h2v4z"/></svg>
                            맞춤형 추천 사유
                        </div>
                        {item.get('recommendation_reason')}
                    </div>
                </div>

                <div class="pt-3 border-t border-slate-100 flex items-center justify-between text-xs">
                    <span class="text-slate-500 font-medium truncate max-w-[150px]">{item.get('source_name')} · {item.get('date')}</span>
                    <a href="{item.get('source_url')}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 px-3 py-1.5 bg-indigo-50 text-indigo-700 hover:bg-indigo-600 hover:text-white rounded-lg font-semibold transition-all">
                        <span>원문 보기</span>
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                    </a>
                </div>
            </div>
            """

        table_rows_html = ""
        for item in recommended:
            rank = int(item.get("rank", 1))
            score = float(item.get("total_score", 0))
            cat = item.get("category", "market")
            cm = cat_meta.get(cat, {"label": cat, "badge": "bg-slate-100 text-slate-800"})

            table_rows_html += f"""
            <tr class="hover:bg-slate-50 transition-colors border-b border-slate-100 text-xs group" data-category="{cat}">
                <td class="py-3 px-4 font-bold text-slate-700 text-center">{rank}</td>
                <td class="py-3 px-4 text-center">
                    <span class="px-2 py-0.5 rounded-full font-semibold {cm['badge']}">{cm['label']}</span>
                </td>
                <td class="py-3 px-4 font-extrabold text-indigo-600 text-center">{score:.1f}</td>
                <td class="py-3 px-4 text-slate-900 font-medium max-w-md">
                    <div class="font-bold text-slate-900 group-hover:text-indigo-600 transition-colors mb-1">{item.get('title')}</div>
                    <div class="text-slate-500 text-[11px] leading-tight line-clamp-1">{item.get('recommendation_reason')}</div>
                </td>
                <td class="py-3 px-4 text-slate-500 whitespace-nowrap text-center">{item.get('source_name')}</td>
                <td class="py-3 px-4 text-slate-400 whitespace-nowrap text-center">{item.get('date')}</td>
                <td class="py-3 px-4 text-center whitespace-nowrap">
                    <a href="{item.get('source_url')}" target="_blank" rel="noopener noreferrer" class="text-indigo-600 hover:text-indigo-800 font-semibold inline-flex items-center gap-1 hover:underline">
                        링크
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>
                    </a>
                </td>
            </tr>
            """

        cat_stats_html = ""
        for c, count in top30_cat_counts.items():
            cm = cat_meta.get(c, {"label": c, "badge": "bg-slate-100 text-slate-800", "bg": "bg-slate-500", "text": "text-slate-600"})
            pct = round(count / len(recommended) * 100, 1)
            cat_stats_html += f"""
            <div class="bg-white p-4 rounded-xl border border-slate-100 shadow-sm flex items-center justify-between">
                <div>
                    <div class="text-xs font-semibold text-slate-400 mb-1">{cm['label']}</div>
                    <div class="text-xl font-extrabold text-slate-900">{count}<span class="text-xs text-slate-400 font-normal ml-1">건 ({pct}%)</span></div>
                </div>
                <div class="w-3 h-10 rounded-full {cm['bg']}"></div>
            </div>
            """

        html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{company_name} - 시장·경쟁사 인텔리전스 대시보드</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" />
    <style>
        body {{ font-family: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif; }}
    </style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen">

    <header class="bg-white border-b border-slate-200 sticky top-0 z-50 shadow-sm backdrop-blur-md bg-white/90">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center text-white shadow-indigo-200 shadow-md">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                </div>
                <div>
                    <h1 class="text-lg font-bold text-slate-900 leading-tight">{company_name} Intelligence Hub</h1>
                    <p class="text-xs text-slate-500">{business_area} 맞춤형 실시간 시장·경쟁사 리포트</p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                    <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                    Live Dashboard
                </span>
                <a href="report.json" target="_blank" class="px-3 py-1.5 text-xs font-semibold text-slate-600 hover:text-indigo-600 bg-slate-100 hover:bg-indigo-50 rounded-lg transition-colors border border-slate-200">
                    report.json API
                </a>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">

        <section class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
                <div class="text-xs font-semibold text-slate-400 mb-1">총 수집 분석 기사</div>
                <div class="text-2xl font-black text-slate-900">{total_analyzed:,}<span class="text-sm font-normal text-slate-400 ml-1">건</span></div>
                <div class="mt-2 text-[11px] text-emerald-600 font-semibold flex items-center gap-1">
                    <span>100% 공개 Source 정제 완료</span>
                </div>
            </div>
            <div class="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
                <div class="text-xs font-semibold text-slate-400 mb-1">최종 선별 추천 기사</div>
                <div class="text-2xl font-black text-indigo-600">{recommended_count}<span class="text-sm font-normal text-slate-400 ml-1">건</span></div>
                <div class="mt-2 text-[11px] text-slate-500 font-medium">
                    다면 적합도 상위 30건 엄선
                </div>
            </div>
            <div class="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
                <div class="text-xs font-semibold text-slate-400 mb-1">최고 관련성 스코어</div>
                <div class="text-2xl font-black text-rose-600">{highest_score}<span class="text-sm font-normal text-slate-400 ml-1">점</span></div>
                <div class="mt-2 text-[11px] text-slate-500 font-medium">
                    100점 만점 기준 평가
                </div>
            </div>
            <div class="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
                <div class="text-xs font-semibold text-slate-400 mb-1">인텔리전스 엔진</div>
                <div class="text-sm font-bold text-slate-800 truncate" title="{engine_label}">{engine_label}</div>
                <div class="mt-2 text-[11px] text-indigo-600 font-semibold flex items-center gap-1">
                    <span>기업 프로필 기반 4대 축 매칭</span>
                </div>
            </div>
        </section>

        <section class="space-y-3">
            <h2 class="text-sm font-bold text-slate-500 uppercase tracking-wider">추천 기사 카테고리 구성 (TOP 30)</h2>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                {cat_stats_html}
            </div>
        </section>

        <section class="space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h2 class="text-xl font-black text-slate-900 tracking-tight flex items-center gap-2">
                        <span>🔥 TOP 10 핵심 추천 인텔리전스</span>
                    </h2>
                    <p class="text-xs text-slate-500 mt-0.5">NovaFactory AI 비즈니스와 가장 밀접한 상위 10대 핵심 기사 및 전략적 추천 사유</p>
                </div>
                <span class="text-xs text-slate-400">실시간 순위 기준</span>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                {top10_html}
            </div>
        </section>

        <section class="bg-white rounded-2xl border border-slate-200/80 shadow-sm overflow-hidden space-y-4 p-6">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <h2 class="text-lg font-bold text-slate-900">전체 추천 리스트 (TOP 30)</h2>
                    <p class="text-xs text-slate-500">카테고리별 필터 및 검색으로 원하는 인텔리전스를 탐색하세요</p>
                </div>

                <div class="flex items-center gap-2">
                    <input type="text" id="searchInput" placeholder="제목/키워드 검색..." class="text-xs px-3 py-2 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 w-48">
                    <select id="categoryFilter" class="text-xs px-3 py-2 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 bg-white">
                        <option value="all">모든 카테고리</option>
                        <option value="competitor">경쟁사 동향</option>
                        <option value="technology">기술 동향</option>
                        <option value="market">시장 트렌드</option>
                        <option value="funding">정부지원/펀딩</option>
                        <option value="policy">정책/규제</option>
                    </select>
                </div>
            </div>

            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse" id="dataTable">
                    <thead>
                        <tr class="bg-slate-50 text-[11px] font-bold text-slate-500 uppercase tracking-wider border-y border-slate-200">
                            <th class="py-3 px-4 text-center w-12">순위</th>
                            <th class="py-3 px-4 text-center w-28">카테고리</th>
                            <th class="py-3 px-4 text-center w-16">점수</th>
                            <th class="py-3 px-4">기사 제목 및 추천 사유</th>
                            <th class="py-3 px-4 text-center w-28">출처</th>
                            <th class="py-3 px-4 text-center w-24">발행일</th>
                            <th class="py-3 px-4 text-center w-16">원문</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        {table_rows_html}
                    </tbody>
                </table>
            </div>
        </section>

    </main>

    <footer class="border-t border-slate-200 bg-white py-8 mt-12 text-center text-xs text-slate-500 space-y-2">
        <p class="font-semibold text-slate-700">© 2026 {company_name} Market Agent. Built with Google Antigravity & GenAI.</p>
        <p class="text-slate-400">본 대시보드는 GitHub Pages에 정적으로 호스팅될 수 있도록 완전히 자립된(Self-contained) 정적 파일로 구성되었습니다.</p>
    </footer>

    <script>
        const searchInput = document.getElementById('searchInput');
        const categoryFilter = document.getElementById('categoryFilter');
        const rows = document.querySelectorAll('#dataTable tbody tr');

        function filterTable() {{
            const query = searchInput.value.toLowerCase();
            const cat = categoryFilter.value;

            rows.forEach(row => {{
                const text = row.innerText.toLowerCase();
                const rowCat = row.getAttribute('data-category');
                const matchesQuery = text.includes(query);
                const matchesCat = (cat === 'all' || rowCat === cat);

                if (matchesQuery && matchesCat) {{
                    row.style.display = '';
                }} else {{
                    row.style.display = 'none';
                }}
            }});
        }}

        searchInput.addEventListener('input', filterTable);
        categoryFilter.addEventListener('change', filterTable);
    </script>
</body>
</html>
"""

        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        self.logger.info(f"docs/index.html 저장 완료: {html_file}")

        try:
            alt = self.base_dir.parent / "docs" / "index.html" if "project1" in str(self.base_dir) else self.base_dir / "project1" / "docs" / "index.html"
            alt.parent.mkdir(parents=True, exist_ok=True)
            with open(alt, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception:
            pass

        return html_file

    def build(self) -> Dict[str, Any]:
        """정적 사이트 빌드 실행"""
        self.logger.info("=========================================================")
        self.logger.info(" [SiteBuilder] GitHub Pages 정적 리포트 빌드 시작")
        self.logger.info("=========================================================")

        recommended, cleaned = self.load_data()
        llm_used = bool(os.environ.get("GEMINI_API_KEY"))

        json_path = self.generate_report_json(recommended, cleaned, llm_used=llm_used)
        html_path = self.generate_html_dashboard(recommended, cleaned, llm_used=llm_used)

        self.logger.info("=========================================================")
        self.logger.info(" [SiteBuilder 완료] 대시보드 빌드 성공")
        self.logger.info(f" - JSON: {json_path}")
        self.logger.info(f" - HTML: {html_path}")
        self.logger.info("=========================================================")

        return {
            "html_path": str(html_path),
            "json_path": str(json_path),
            "total_recommended": len(recommended),
            "top_10": recommended[:10],
            "llm_used": llm_used
        }


if __name__ == "__main__":
    builder = SiteBuilder()
    res = builder.build()

    print("\n" + "=" * 60)
    print(" [STATIC SITE BUILD SUMMARY REPORT]")
    print("=" * 60)
    print(f"[*] 웹 대시보드 : {res['html_path']}")
    print(f"[*] JSON 리포트 : {res['json_path']}")
    print(f"[*] 추천 건수   : {res['total_recommended']}건")
    print(f"[*] LLM 사용 여부: {'사용' if res['llm_used'] else '미사용 (규칙 기반)'}")
    print("=" * 60)
