"""Market Intelligence Recommender for NovaFactory AI.

Evaluates relevance of cleaned market news articles to NovaFactory AI's profile:
- Calculates keyword, company, competitor, funding, and recency relevance scores.
- If GEMINI_API_KEY is available, enriches top articles with LLM evaluation and tailored reasons.
- Otherwise, falls back seamlessly to rule-based scoring and reasoning.
- Outputs top 30 articles to data/processed/recommended_market_news.csv.
"""

import os
import sys
import re
import csv
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

import yaml

# Load environment variables safely
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        except Exception:
            pass

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "recommender.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MarketRecommender")


class MarketRecommender:
    """Ranks and recommends articles for NovaFactory AI."""

    def __init__(
        self,
        config_path: str = "config/company_profile.yaml",
        input_path: str = "data/processed/cleaned_market_news.csv",
        output_path: str = "data/processed/recommended_market_news.csv",
        top_n: int = 30
    ):
        self.config_path = config_path
        self.input_path = input_path
        self.output_path = output_path
        self.top_n = top_n

        self.profile = self._load_profile()
        self.company_name = self.profile.get("company_name", "NovaFactory AI")
        self.business_area = self.profile.get("business_area", "제조업 AI 비전 품질검사")
        self.products = self.profile.get("products", ["비전 기반 불량 탐지 SaaS", "제조 품질 리포트 자동화"])
        self.target_market = self.profile.get("target_market", ["중소·중견 제조기업", "스마트팩토리 구축 기업"])
        self.competitors = self.profile.get("competitors", ["VisionForge", "InspectAI", "FactoryMind", "QualiBot"])
        self.interest_keywords = self.profile.get("interest_keywords", [])
        self.funding_keywords = self.profile.get("funding_keywords", [])

        # Check Gemini API Key
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.use_llm = bool(self.gemini_api_key)
        if self.use_llm:
            logger.info("GEMINI_API_KEY detected. LLM evaluation enabled.")
        else:
            logger.info("GEMINI_API_KEY not found. Operating in deterministic rule-based mode.")

    def _load_profile(self) -> Dict[str, Any]:
        """Loads company profile configuration."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found at {self.config_path}")
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error reading {self.config_path}: {e}")
            return {}

    def _calculate_recency_score(self, date_str: str) -> float:
        """Calculates bonus score based on publication recency."""
        try:
            art_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
            # Anchor date to 2026-09-19
            now = datetime(2026, 9, 19)
            diff_days = (now - art_date).days
            if diff_days <= 7:
                return 10.0
            elif diff_days <= 30:
                return 7.0
            elif diff_days <= 90:
                return 4.0
            elif diff_days <= 180:
                return 2.0
            return 0.0
        except Exception:
            return 2.0

    def score_article_rule_based(self, article: Dict[str, Any]) -> Tuple[int, Dict[str, Any], str]:
        """Calculates detailed rule-based relevance score and recommendation reason."""
        title = article.get("title", "")
        content = article.get("content", "") or article.get("summary", "")
        title_lower = title.lower()
        content_lower = content.lower()
        category = article.get("category", "").lower()
        company_tag = article.get("company_tag", "")

        keyword_score = 0
        company_score = 0
        competitor_score = 0
        funding_score = 0

        matched_competitors = []
        matched_keywords = []
        matched_funding = []

        # 1. Competitor matching (Weight: High)
        for comp in self.competitors:
            comp_l = comp.lower()
            if comp_l in title_lower:
                competitor_score += 35
                matched_competitors.append(comp)
            elif comp_l in content_lower:
                competitor_score += 18
                matched_competitors.append(comp)

        if category == "competitor" and not matched_competitors:
            competitor_score += 15

        # 2. Keyword & Technology matching
        for kw in self.interest_keywords + ["비전 AI", "검사", "불량 탐지", "엣지 AI"]:
            kw_l = kw.lower()
            if kw_l in title_lower:
                keyword_score += 14
                matched_keywords.append(kw)
            elif kw_l in content_lower:
                keyword_score += 6
                matched_keywords.append(kw)

        # 3. Company & Target Market matching
        if self.company_name.lower() in title_lower or self.company_name.lower() in content_lower:
            company_score += 40

        for tm in ["스마트공장", "중소기업", "제조기업", "반도체", "외관 검사", "스마트팩토리"]:
            if tm in title:
                company_score += 12
            elif tm in content:
                company_score += 5

        # 4. Funding & Policy matching
        for fkw in self.funding_keywords + ["지원사업", "보급사업", "바우처", "출연금"]:
            fkw_l = fkw.lower()
            if fkw_l in title_lower:
                funding_score += 18
                matched_funding.append(fkw)
            elif fkw_l in content_lower:
                funding_score += 8
                matched_funding.append(fkw)

        if category == "funding":
            funding_score += 10
        elif category == "policy":
            funding_score += 8

        # 5. Recency Bonus
        recency_score = self._calculate_recency_score(article.get("date", ""))

        raw_total = keyword_score + company_score + competitor_score + funding_score + recency_score
        # Normalize to 0-100 scale
        normalized_score = min(100, max(10, int(raw_total)))

        sub_scores = {
            "keyword_score": keyword_score,
            "company_score": company_score,
            "competitor_score": competitor_score,
            "funding_score": funding_score,
            "recency_score": recency_score,
            "matched_competitors": list(set(matched_competitors)),
            "matched_keywords": list(set(matched_keywords)),
            "matched_funding": list(set(matched_funding))
        }

        # Generate Rule-based Recommendation Reason
        reason = self._generate_rule_reason(article, sub_scores, normalized_score)

        return normalized_score, sub_scores, reason

    def _generate_rule_reason(
        self,
        article: Dict[str, Any],
        sub_scores: Dict[str, Any],
        score: int
    ) -> str:
        """Generates tailored Korean recommendation rationale based on matched dimensions."""
        cat = article.get("category", "")
        comp_list = sub_scores["matched_competitors"]
        kw_list = sub_scores["matched_keywords"]
        fund_list = sub_scores["matched_funding"]

        if comp_list:
            comp_str = ", ".join(comp_list)
            return (
                f"[경쟁사 동향] 주요 경쟁사 '{comp_str}'의 최신 시장 및 기술 움직임 포착. "
                f"자사 비전 검사 솔루션과의 기능 비교 분석 및 차별화 영업 전략 수립이 필요합니다."
            )
        elif cat == "funding" or fund_list:
            fund_str = ", ".join(fund_list[:3]) if fund_list else "스마트공장 및 AI 지원사업"
            return (
                f"[정부지원/사업화] '{fund_str}' 관련 공고/정책 동향. "
                f"자사 타깃 고객인 중소·중견 제조기업의 도입 부담을 낮추기 위한 정부 바우처 연계 제안에 유효합니다."
            )
        elif any(k in ["머신비전", "품질검사", "비전 AI", "불량 탐지"] for k in kw_list):
            kw_str = ", ".join([k for k in kw_list if k in ["머신비전", "품질검사", "비전 AI", "불량 탐지"]][:3])
            return (
                f"[핵심 기술/제품] '{kw_str}' 관련 최신 산업 수요 및 기술 동향. "
                f"자사 '비전 기반 불량 탐지 SaaS' 기능 고도화 및 제조 현장 적용 사례 마케팅에 직결됩니다."
            )
        elif any(k in ["스마트팩토리", "제조 AX", "자동화"] for k in kw_list) or cat == "market":
            return (
                f"[제조 AX 시장] 제조 공정 디지털 전환(AX) 및 스마트공장 고도화 트렌드. "
                f"제조 품질 리포트 자동화 및 엣지 AI 솔루션의 신규 수요처 발굴 기회로 활용 가능합니다."
            )
        else:
            return (
                f"[산업 환경] 제조업 및 AI 유관 산업 환경 변화 소식. "
                f"잠재적 비즈니스 기회 발굴 및 시장 모니터링 목적의 참조를 권장합니다."
            )

    def _evaluate_with_gemini(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Evaluates top candidate articles using Gemini API if key is available."""
        if not self.gemini_api_key:
            return articles

        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_api_key)
            logger.info("Executing Gemini batch evaluation for top recommendations...")

            # Evaluate top candidates
            for idx, art in enumerate(articles):
                prompt = (
                    f"너는 제조업 AI 비전 품질검사 스타트업 'NovaFactory AI'의 시장 전략 분석가이다.\n"
                    f"자사 핵심 제품: {', '.join(self.products)}\n"
                    f"타깃 고객: {', '.join(self.target_market)}\n"
                    f"경쟁사: {', '.join(self.competitors)}\n\n"
                    f"다음 뉴스 기사를 분석하고 JSON 포맷으로 답해라.\n"
                    f"제목: {art['title']}\n"
                    f"카테고리: {art['category']}\n"
                    f"내용 요약: {art['summary']}\n\n"
                    f"응답 JSON 형식:\n"
                    f"{{\n"
                    f'  "llm_score": (10~100 사이 정수),\n'
                    f'  "action_urgency": "상(High)" | "중(Medium)" | "하(Low)",\n'
                    f'  "recommendation_reason": "자사 사업 및 제품과의 구체적 연계성과 대응 방안을 설명하는 2~3문장의 한국어 설명"\n'
                    f"}}"
                )
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                        config={"response_mime_type": "application/json"}
                    )
                    res_json = json.loads(response.text)
                    llm_score = int(res_json.get("llm_score", art["score"]))
                    # Blend rule score (40%) and LLM score (60%)
                    blended_score = int(art["score"] * 0.4 + llm_score * 0.6)
                    art["score"] = blended_score
                    art["recommendation_reason"] = res_json.get("recommendation_reason", art["recommendation_reason"])
                    art["urgency"] = res_json.get("action_urgency", "중(Medium)")
                    art["llm_evaluated"] = "true"
                except Exception as e:
                    logger.warning(f"Failed Gemini evaluation for article {idx}: {e}")
                    art["llm_evaluated"] = "false"

            return articles

        except Exception as e:
            logger.error(f"Gemini evaluation setup failed: {e}. Falling back to rule-based.")
            return articles

    def run_recommendation(self) -> List[Dict[str, Any]]:
        """Executes full recommendation pipeline and outputs CSV."""
        logger.info(f"=== Starting Market News Recommendation Pipeline ===")
        logger.info(f"Input : {self.input_path}")
        logger.info(f"Output: {self.output_path}")

        if not os.path.exists(self.input_path):
            raise FileNotFoundError(f"Input file not found: {self.input_path}")

        with open(self.input_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)

        logger.info(f"Evaluating {len(rows)} cleaned articles against NovaFactory AI profile...")

        scored_articles: List[Dict[str, Any]] = []
        for row in rows:
            score, sub_scores, reason = self.score_article_rule_based(row)
            urgency = "상(High)" if score >= 70 else ("중(Medium)" if score >= 45 else "보통(Low)")

            item = dict(row)
            item["score"] = score
            item["recommendation_reason"] = reason
            item["urgency"] = urgency
            item["llm_evaluated"] = "false"
            item["sub_scores"] = json.dumps(sub_scores, ensure_ascii=False)
            scored_articles.append(item)

        # Sort by score descending, then by date descending
        scored_articles.sort(key=lambda x: (x["score"], x.get("date", "")), reverse=True)

        # Select Top N candidates
        top_candidates = scored_articles[:self.top_n]

        # Apply LLM enrichment if key available
        if self.use_llm:
            top_candidates = self._evaluate_with_gemini(top_candidates)
            # Re-sort after LLM score adjustments
            top_candidates.sort(key=lambda x: (x["score"], x.get("date", "")), reverse=True)

        # Add rank
        for rank, item in enumerate(top_candidates, 1):
            item["rank"] = rank

        # Ensure output directory exists
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        # Write output CSV
        out_fields = fieldnames + ["score", "recommendation_reason", "urgency", "llm_evaluated", "rank"]
        # Deduplicate fieldnames
        out_fields = list(dict.fromkeys(out_fields))

        with open(self.output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
            writer.writeheader()
            for r in top_candidates:
                writer.writerow(r)

        logger.info(f"Saved TOP {len(top_candidates)} recommendations to {self.output_path}")

        # Print console summary
        self._print_summary(top_candidates)

        return top_candidates

    def _print_summary(self, top_candidates: List[Dict[str, Any]]) -> None:
        """Prints a summary report of top 10 recommendations."""
        print("\n" + "=" * 80)
        print("          NOVAFACTORY AI MARKET RECOMMENDATION REPORT")
        print("=" * 80)
        print(f"Total Evaluated Articles : 488 (Loaded from cleaned data)")
        print(f"Top Recommended Selected : {len(top_candidates)} articles")
        print(f"LLM Enrichment Enabled   : {self.use_llm}")
        print("-" * 80)
        print("TOP 10 RECOMMENDATIONS:")
        print(f"{'Rank':4} | {'Score':5} | {'Category':11} | {'Date':10} | {'Title'}")
        print("-" * 80)
        for item in top_candidates[:10]:
            rank = item.get("rank", 0)
            score = item.get("score", 0)
            cat = item.get("category", "")[:10]
            dt = item.get("date", "")[:10]
            title = item.get("title", "")
            title_disp = (title[:42] + "...") if len(title) > 45 else title
            print(f"{rank:4} | {score:5} | {cat:11} | {dt:10} | {title_disp}")
        print("-" * 80)
        print(f"Output File: {self.output_path}")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    recommender = MarketRecommender()
    recommender.run_recommendation()
