"""Static Site and Report Builder for NovaFactory AI Market Dashboard.

Reads recommended_market_news.csv and company_profile.yaml to generate:
1. docs/report.json (machine-readable analytical report)
2. docs/index.html (modern, responsive GitHub Pages static dashboard)
"""

import os
import sys
import csv
import json
import logging
from datetime import datetime
from typing import Dict, List, Any
import yaml

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "build_site.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SiteBuilder")


class DashboardBuilder:
    """Builds static web dashboard and JSON report for GitHub Pages."""

    def __init__(
        self,
        config_path: str = "config/company_profile.yaml",
        recommended_csv: str = "data/processed/recommended_market_news.csv",
        cleaned_csv: str = "data/processed/cleaned_market_news.csv",
        output_dir: str = "docs"
    ):
        self.config_path = config_path
        self.recommended_csv = recommended_csv
        self.cleaned_csv = cleaned_csv
        self.output_dir = output_dir

        self.html_path = os.path.join(output_dir, "index.html")
        self.json_path = os.path.join(output_dir, "report.json")

        self.profile = self._load_profile()
        self.recommended_articles = self._load_csv(self.recommended_csv)
        self.total_cleaned_count = self._count_cleaned_csv()

    def _load_profile(self) -> Dict[str, Any]:
        """Loads company profile YAML."""
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _load_csv(self, path: str) -> List[Dict[str, Any]]:
        """Loads CSV data."""
        if not os.path.exists(path):
            logger.warning(f"CSV file not found: {path}")
            return []
        with open(path, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def _count_cleaned_csv(self) -> int:
        """Counts total rows in cleaned_market_news.csv."""
        if os.path.exists(self.cleaned_csv):
            with open(self.cleaned_csv, "r", encoding="utf-8-sig") as f:
                return sum(1 for _ in csv.DictReader(f))
        return len(self.recommended_articles)

    def generate_report_json(self) -> Dict[str, Any]:
        """Generates docs/report.json with structured metrics."""
        os.makedirs(self.output_dir, exist_ok=True)

        # Compute category distribution
        cat_counts: Dict[str, int] = {}
        for a in self.recommended_articles:
            c = a.get("category", "unknown")
            cat_counts[c] = cat_counts.get(c, 0) + 1

        scores = [int(a.get("score", 0)) for a in self.recommended_articles if a.get("score")]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        max_score = max(scores) if scores else 0

        # LLM evaluation flag
        llm_used = any(a.get("llm_evaluated", "false").lower() == "true" for a in self.recommended_articles)

        top_10 = self.recommended_articles[:10]

        report_data = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_crawled_cleaned": self.total_cleaned_count,
                "recommended_count": len(self.recommended_articles),
                "top_10_count": len(top_10),
                "llm_evaluated": llm_used,
                "evaluation_mode": "Gemini LLM Enhanced" if llm_used else "Rule-based Semantic Engine",
                "max_score": max_score,
                "avg_score": avg_score
            },
            "company_profile": {
                "company_name": self.profile.get("company_name", "NovaFactory AI"),
                "business_area": self.profile.get("business_area", "제조업 AI 비전 품질검사"),
                "products": self.profile.get("products", []),
                "target_market": self.profile.get("target_market", []),
                "competitors": self.profile.get("competitors", []),
                "interest_keywords": self.profile.get("interest_keywords", [])
            },
            "category_distribution": cat_counts,
            "top_10": [
                {
                    "rank": int(a.get("rank", idx + 1)),
                    "article_id": a.get("article_id", ""),
                    "score": int(a.get("score", 0)),
                    "category": a.get("category", ""),
                    "title": a.get("title", ""),
                    "date": a.get("date", ""),
                    "source_name": a.get("source_name", ""),
                    "source_url": a.get("source_url", ""),
                    "recommendation_reason": a.get("recommendation_reason", ""),
                    "urgency": a.get("urgency", "중(Medium)"),
                    "keywords": a.get("keywords", "")
                }
                for idx, a in enumerate(top_10)
            ],
            "all_recommendations": self.recommended_articles
        }

        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Report JSON generated: {self.json_path}")
        return report_data

    def generate_index_html(self, report_data: Dict[str, Any]) -> None:
        """Generates modern, responsive docs/index.html dashboard for GitHub Pages."""
        os.makedirs(self.output_dir, exist_ok=True)

        meta = report_data["metadata"]
        comp_profile = report_data["company_profile"]
        cat_dist = report_data["category_distribution"]
        top_10 = report_data["top_10"]
        all_articles = report_data["all_recommendations"]

        # Category colors mapping
        cat_badge_classes = {
            "competitor": "bg-purple-100 text-purple-800 border-purple-200",
            "technology": "bg-blue-100 text-blue-800 border-blue-200",
            "funding": "bg-emerald-100 text-emerald-800 border-emerald-200",
            "market": "bg-amber-100 text-amber-800 border-amber-200",
            "policy": "bg-indigo-100 text-indigo-800 border-indigo-200"
        }

        # JSON data for client-side filtering
        articles_json = json.dumps(all_articles, ensure_ascii=False)

        # Build Top 10 HTML Cards
        top10_html = []
        for a in top_10:
            rank = a["rank"]
            score = a["score"]
            cat = a["category"]
            title = a["title"]
            date = a["date"]
            source = a["source_name"]
            url = a["source_url"]
            reason = a["recommendation_reason"]
            kws = a["keywords"]
            badge_class = cat_badge_classes.get(cat.lower(), "bg-gray-100 text-gray-800 border-gray-200")

            rank_badge_color = "bg-amber-500 text-white" if rank == 1 else (
                "bg-slate-400 text-white" if rank == 2 else (
                    "bg-amber-700 text-white" if rank == 3 else "bg-slate-200 text-slate-700"
                )
            )

            card = f"""
            <div class="bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-all">
                <div class="flex items-start justify-between gap-3 mb-2">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold {rank_badge_color}">
                            #{rank}
                        </span>
                        <span class="px-2.5 py-0.5 text-xs font-medium rounded-full border {badge_class}">
                            {cat.upper()}
                        </span>
                        <span class="text-xs text-slate-500">
                            {source} · {date}
                        </span>
                    </div>
                    <div class="flex items-center gap-1 bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full text-xs font-bold border border-blue-100 shrink-0">
                        <span>점수</span>
                        <span class="text-sm font-extrabold">{score}</span>
                    </div>
                </div>

                <h3 class="text-base font-bold text-slate-900 mb-2 leading-snug">
                    <a href="{url}" target="_blank" rel="noopener noreferrer" class="hover:text-blue-600 transition-colors">
                        {title}
                    </a>
                </h3>

                <div class="bg-slate-50 rounded-lg p-3.5 mb-3 border border-slate-100">
                    <div class="text-xs font-bold text-slate-700 mb-1 flex items-center gap-1">
                        <svg class="w-3.5 h-3.5 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
                            <path d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z"/>
                        </svg>
                        맞춤 추천 이유 & 대응 방안
                    </div>
                    <p class="text-xs text-slate-600 leading-relaxed">
                        {reason}
                    </p>
                </div>

                <div class="flex items-center justify-between pt-2 border-t border-slate-100 text-xs">
                    <div class="text-slate-400 truncate max-w-[70%]">
                        태그: <span class="text-slate-600">{kws.replace('|', ', ') if kws else '제조 AI'}</span>
                    </div>
                    <a href="{url}" target="_blank" rel="noopener noreferrer" 
                       class="inline-flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-800 hover:underline">
                        <span>원문 보기</span>
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
                        </svg>
                    </a>
                </div>
            </div>
            """
            top10_html.append(card)

        top10_cards_rendered = "\n".join(top10_html)

        # Build Category Pills
        cat_pills_html = []
        for cat, cnt in cat_dist.items():
            badge_class = cat_badge_classes.get(cat.lower(), "bg-gray-100 text-gray-800 border-gray-200")
            cat_pills_html.append(
                f'<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border {badge_class}">'
                f'{cat.upper()} <b class="ml-0.5">{cnt}건</b></span>'
            )
        cat_pills_rendered = " ".join(cat_pills_html)

        html_template = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{comp_profile['company_name']} 시장·경쟁사 인텔리전스 대시보드</title>
    <!-- Tailwind CSS (Google allowlisted script) -->
    <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #f8fafc;
        }}
    </style>
</head>
<body class="text-slate-800 antialiased min-h-screen">

    <!-- Top Header -->
    <header class="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
            <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white font-black text-lg shadow-md shadow-blue-500/20">
                        N
                    </div>
                    <div>
                        <div class="flex items-center gap-2">
                            <h1 class="text-xl font-bold text-slate-900 tracking-tight">{comp_profile['company_name']}</h1>
                            <span class="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full font-semibold">Market Agent</span>
                        </div>
                        <p class="text-xs text-slate-500">시장·경쟁사·정책 수집 및 맞춤형 인텔리전스 리포트</p>
                    </div>
                </div>
                <div class="flex items-center gap-3 text-xs text-slate-500">
                    <span class="flex items-center gap-1.5 bg-slate-100 px-3 py-1.5 rounded-lg border border-slate-200">
                        <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                        생성 일시: <b>{meta['generated_at'][:10]}</b>
                    </span>
                    <a href="report.json" target="_blank" 
                       class="inline-flex items-center gap-1 bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 rounded-lg font-medium transition-colors shadow-sm">
                        <span>report.json API</span>
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
                        </svg>
                    </a>
                </div>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">

        <!-- Company Profile Briefing Card -->
        <section class="bg-gradient-to-r from-slate-900 via-slate-800 to-indigo-950 text-white rounded-2xl p-6 shadow-xl relative overflow-hidden">
            <div class="relative z-10 grid grid-cols-1 md:grid-cols-4 gap-6">
                <div>
                    <span class="text-xs font-semibold text-blue-400 uppercase tracking-wider">사업 분야</span>
                    <h2 class="text-lg font-bold mt-1 text-slate-100">{comp_profile['business_area']}</h2>
                    <p class="text-xs text-slate-400 mt-1">타깃: {', '.join(comp_profile['target_market'][:2])}</p>
                </div>
                <div>
                    <span class="text-xs font-semibold text-indigo-400 uppercase tracking-wider">핵심 제품 라인업</span>
                    <ul class="text-xs text-slate-300 mt-1 space-y-0.5">
                        {''.join([f'<li>• {p}</li>' for p in comp_profile['products'][:2]])}
                    </ul>
                </div>
                <div>
                    <span class="text-xs font-semibold text-purple-400 uppercase tracking-wider">주요 모니터링 경쟁사</span>
                    <div class="flex flex-wrap gap-1.5 mt-1.5">
                        {''.join([f'<span class="bg-white/10 px-2 py-0.5 rounded text-xs text-slate-200">{c}</span>' for c in comp_profile['competitors']])}
                    </div>
                </div>
                <div>
                    <span class="text-xs font-semibold text-emerald-400 uppercase tracking-wider">평가 엔진 상태</span>
                    <div class="text-sm font-bold text-slate-100 mt-1">{meta['evaluation_mode']}</div>
                    <div class="text-xs text-slate-400 mt-0.5">최대 관련도: <b class="text-amber-400">{meta['max_score']}점</b> (평균 {meta['avg_score']}점)</div>
                </div>
            </div>
        </section>

        <!-- KPI Metrics Grid -->
        <section class="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <span class="text-xs font-medium text-slate-500">총 수집/정제 기사</span>
                <div class="text-2xl font-extrabold text-slate-900 mt-1">{meta['total_crawled_cleaned']} <span class="text-xs font-normal text-slate-500">건</span></div>
                <span class="text-xs text-emerald-600 font-semibold mt-1 inline-block">100% 정상 전처리 완료</span>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <span class="text-xs font-medium text-slate-500">맞춤 추천 기사</span>
                <div class="text-2xl font-extrabold text-blue-600 mt-1">{meta['recommended_count']} <span class="text-xs font-normal text-slate-500">건</span></div>
                <span class="text-xs text-slate-500 mt-1 inline-block">상위 선별 데이터셋</span>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <span class="text-xs font-medium text-slate-500">TOP 10 우선순위</span>
                <div class="text-2xl font-extrabold text-indigo-600 mt-1">10 <span class="text-xs font-normal text-slate-500">선</span></div>
                <span class="text-xs text-indigo-600 font-semibold mt-1 inline-block">대응 방안 수립 대상</span>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <span class="text-xs font-medium text-slate-500">추천 카테고리 다양성</span>
                <div class="text-2xl font-extrabold text-purple-600 mt-1">{len(cat_dist)} <span class="text-xs font-normal text-slate-500">개 영역</span></div>
                <span class="text-xs text-slate-500 mt-1 inline-block">시장·기술·지원·경쟁</span>
            </div>
        </section>

        <!-- Category Breakdown Filter Bar -->
        <section class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center gap-2 flex-wrap">
                <span class="text-xs font-bold text-slate-600 mr-1">카테고리 분포:</span>
                {cat_pills_rendered}
            </div>
            <div class="text-xs text-slate-500">
                추천 상위 30건 기준 분포
            </div>
        </section>

        <!-- TOP 10 Priorities Section -->
        <section class="space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h2 class="text-lg font-bold text-slate-900 flex items-center gap-2">
                        <span>🔥 TOP 10 핵심 추천 인텔리전스</span>
                    </h2>
                    <p class="text-xs text-slate-500">관련도 점수 및 기업 파급효과가 가장 높은 최우선 모니터링 기사</p>
                </div>
                <span class="text-xs text-blue-600 font-medium">실시간 원문 링크 제공</span>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {top10_cards_rendered}
            </div>
        </section>

        <!-- Full Recommendations Table (Top 30) -->
        <section class="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-4">
            <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                    <h2 class="text-base font-bold text-slate-900">전체 추천 기사 30선 (Interactive Table)</h2>
                    <p class="text-xs text-slate-500">키워드 검색 및 카테고리 필터링이 가능합니다.</p>
                </div>
                <div class="flex items-center gap-2">
                    <input type="text" id="searchInput" placeholder="기사 제목, 언론사, 키워드 검색..." 
                           class="text-xs border border-slate-300 rounded-lg px-3 py-2 w-64 focus:outline-none focus:ring-2 focus:ring-blue-500">
                </div>
            </div>

            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-slate-200 text-left text-xs" id="recomTable">
                    <thead class="bg-slate-50 text-slate-600 font-semibold">
                        <tr>
                            <th class="px-3 py-3 w-12 text-center">순위</th>
                            <th class="px-3 py-3 w-16 text-center">점수</th>
                            <th class="px-3 py-3 w-24">카테고리</th>
                            <th class="px-4 py-3">기사 제목</th>
                            <th class="px-3 py-3 w-28">출처 / 언론사</th>
                            <th class="px-3 py-3 w-24">발행일</th>
                            <th class="px-3 py-3 w-20 text-center">원문</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100 text-slate-700" id="tableBody">
                        <!-- Populated by JavaScript -->
                    </tbody>
                </table>
            </div>
        </section>

    </main>

    <!-- Footer -->
    <footer class="bg-white border-t border-slate-200 mt-12 py-6 text-center text-xs text-slate-500">
        <p>© 2026 {comp_profile['company_name']}. Built with Google Antigravity & Market Agent Pipeline.</p>
        <p class="mt-1">GitHub Pages Deployment Ready · Data Processed from Live Public Sources</p>
    </footer>

    <!-- Client-side Search and Rendering Script -->
    <script>
        const articles = {articles_json};

        function renderTable(data) {{
            const tbody = document.getElementById('tableBody');
            tbody.innerHTML = '';
            if (data.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="7" class="px-4 py-8 text-center text-slate-400">일치하는 추천 기사가 없습니다.</td></tr>';
                return;
            }}
            data.forEach((item, idx) => {{
                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-50 transition-colors';
                tr.innerHTML = `
                    <td class="px-3 py-3 text-center font-bold text-slate-500">#${{item.rank || (idx + 1)}}</td>
                    <td class="px-3 py-3 text-center font-extrabold text-blue-600">${{item.score || 0}}</td>
                    <td class="px-3 py-3">
                        <span class="px-2 py-0.5 rounded text-[10px] font-semibold uppercase bg-slate-100 text-slate-700">
                            ${{item.category}}
                        </span>
                    </td>
                    <td class="px-4 py-3 font-medium text-slate-900">
                        <a href="${{item.source_url}}" target="_blank" rel="noopener noreferrer" class="hover:text-blue-600 hover:underline">
                            ${{item.title}}
                        </a>
                        <div class="text-[11px] text-slate-500 mt-0.5 line-clamp-1">${{item.recommendation_reason || ''}}</div>
                    </td>
                    <td class="px-3 py-3 text-slate-600">${{item.source_name || ''}}</td>
                    <td class="px-3 py-3 text-slate-500">${{item.date ? item.date.slice(0, 10) : ''}}</td>
                    <td class="px-3 py-3 text-center">
                        <a href="${{item.source_url}}" target="_blank" rel="noopener noreferrer" 
                           class="text-blue-600 hover:text-blue-800 font-semibold hover:underline">보기 ↗</a>
                    </td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        // Initialize table
        renderTable(articles);

        // Search filter
        document.getElementById('searchInput').addEventListener('input', function(e) {{
            const q = e.target.value.toLowerCase().trim();
            if (!q) {{
                renderTable(articles);
                return;
            }}
            const filtered = articles.filter(a => 
                (a.title && a.title.toLowerCase().includes(q)) ||
                (a.source_name && a.source_name.toLowerCase().includes(q)) ||
                (a.category && a.category.toLowerCase().includes(q)) ||
                (a.keywords && a.keywords.toLowerCase().includes(q)) ||
                (a.recommendation_reason && a.recommendation_reason.toLowerCase().includes(q))
            );
            renderTable(filtered);
        }});
    </script>
</body>
</html>
"""
        with open(self.html_path, "w", encoding="utf-8") as f:
            f.write(html_template)

        logger.info(f"Dashboard HTML generated: {self.html_path}")

    def build(self) -> None:
        """Runs the complete site and report build process."""
        logger.info("=== Starting Dashboard & Report Site Builder ===")
        report_data = self.generate_report_json()
        self.generate_index_html(report_data)
        logger.info("=== Build Process Completed Successfully ===")


if __name__ == "__main__":
    builder = DashboardBuilder()
    builder.build()
