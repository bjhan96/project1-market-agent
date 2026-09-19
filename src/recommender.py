"""
Market & Competitor Intelligence Recommender (기업 맞춤형 인텔리전스 추천 엔진)

- 대상 기업: NovaFactory AI (config/company_profile.yaml)
- 입력 데이터: data/processed/cleaned_market_news.csv
- 출력 데이터: data/processed/recommended_market_news.csv
- 주요 기능:
  1. keyword / company / competitor / funding 다면 관련성 점수 산출
  2. Gemini API Key 존재 시 LLM(Google GenAI SDK) 기반 심층 평가 및 추천 사유 생성
  3. API Key 부재 시 지능형 규칙 기반(Rule-based) 평가 및 맞춤형 추천 사유 자동 생성
  4. 최상위 30개 기사 선별 및 CSV 저장
"""

import os
import sys
import csv
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional

import yaml

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
    log_file = log_dir / "recommender.log"

    logger = logging.getLogger("IntelligenceRecommender")
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


# ---------------------------------------------------------------------------
# MarketNewsRecommender 클래스
# ---------------------------------------------------------------------------
class MarketNewsRecommender:
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
        self.input_file = self.base_dir / "data" / "processed" / "cleaned_market_news.csv"
        self.output_file = self.base_dir / "data" / "processed" / "recommended_market_news.csv"
        self.log_dir = self.base_dir / "logs"

        self.logger = setup_logging(self.log_dir)
        self.config = self._load_config()
        self.llm_used = False

    def _load_config(self) -> Dict[str, Any]:
        """company_profile.yaml 로드"""
        if not self.config_path.exists():
            self.logger.warning(f"설정 파일 미발견: {self.config_path}. 기본 설정 사용.")
            return {
                "company_name": "NovaFactory AI",
                "business_area": "제조업 AI 비전 품질검사",
                "products": ["비전 기반 불량 탐지 SaaS", "제조 품질 리포트 자동화", "엣지 AI 품질 분석 솔루션"],
                "target_market": ["중소·중견 제조기업", "스마트팩토리 구축 기업", "반도체/전자부품 외관 검사 공정"],
                "competitors": ["VisionForge", "InspectAI", "FactoryMind", "QualiBot"],
                "interest_keywords": ["AI", "스마트팩토리", "품질검사", "자동화", "클라우드", "제조 AX", "디지털 전환", "머신비전"],
                "funding_keywords": ["창업지원", "AI 바우처", "스마트공장", "R&D", "사업화 자금", "중소기업 지원"]
            }
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            self.logger.info(f"기업 프로필 로드 완료: {cfg.get('company_name', 'Unknown')}")
            return cfg

    # -----------------------------------------------------------------------
    # 1. 다면 관련성 점수 계산 (Rule-based Scoring)
    # -----------------------------------------------------------------------
    def calculate_relevance_scores(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        keyword, company, competitor, funding 4개 축으로 점수 산출
        - keyword_score: 관심 키워드 매칭도 (최대 35점)
        - company_score: 당사 비즈니스 영역 및 타깃 시장 부합도 (최대 25점)
        - competitor_score: 경쟁사 및 경쟁 생태계 연관도 (최대 20점)
        - funding_score: 정부지원/R&D/사업화 자금 부합도 (최대 20점)
        """
        title = row.get("title", "").lower()
        content = (row.get("content", "") + " " + row.get("summary", "")).lower()
        category = row.get("category", "").lower()
        company_tag = row.get("company_tag", "").lower()

        # -------------------------
        # (1) Keyword Score (최대 35점)
        # -------------------------
        kw_weights = {
            "머신비전": 10, "품질검사": 10, "스마트팩토리": 8, "제조 ax": 8,
            "스마트공장": 8, "외관검사": 8, "불량검사": 8, "결함": 6,
            "ai": 4, "자동화": 5, "디지털 전환": 5, "클라우드": 4
        }
        kw_score = 0
        matched_kws = []
        for kw, weight in kw_weights.items():
            if kw in title:
                kw_score += weight * 1.5  # 제목 포함 가중치 1.5배
                matched_kws.append(kw)
            elif kw in content:
                kw_score += weight
                matched_kws.append(kw)
        keyword_score = min(35.0, kw_score)

        # -------------------------
        # (2) Company & Domain Score (최대 25점)
        # -------------------------
        # 당사 사업 분야: 제조업 AI 비전 품질검사 / SaaS / 엣지 AI / 반도체·전자부품 외관검사
        comp_domain_keywords = {
            "비전": 6, "불량": 6, "검사": 5, "엣지 ai": 8, "edge ai": 8,
            "saas": 6, "반도체": 6, "전자부품": 5, "외관": 6, "표면": 5,
            "제조 ai": 6, "공정": 4, "센서": 4
        }
        co_score = 0
        matched_domain = []
        for term, w in comp_domain_keywords.items():
            if term in title:
                co_score += w * 1.4
                matched_domain.append(term)
            elif term in content:
                co_score += w
                matched_domain.append(term)
        company_score = min(25.0, co_score)

        # -------------------------
        # (3) Competitor Score (최대 20점)
        # -------------------------
        competitors = [c.lower() for c in self.config.get("competitors", [])]
        comp_score = 0
        matched_comp = []
        for comp in competitors:
            if comp in title or comp in content or comp in company_tag:
                comp_score += 20.0  # 지정 경쟁사 직접 언급
                matched_comp.append(comp)

        if comp_score == 0:
            if category == "competitor":
                comp_score += 12.0
            if any(term in title or term in content for term in ["경쟁사", "스타트업", "비전 솔루션", "검사 장비 기업", "머신비전 기업"]):
                comp_score += 6.0
        competitor_score = min(20.0, comp_score)

        # -------------------------
        # (4) Funding / Policy Score (최대 20점)
        # -------------------------
        fund_weights = {
            "ai 바우처": 10, "스마트공장": 8, "r&d": 7, "사업화 자금": 7,
            "창업지원": 6, "중소기업 지원": 6, "바우처": 6, "모집 공고": 6,
            "지원사업": 6, "기술개발": 5, "디지털제조": 5
        }
        fn_score = 0
        matched_fund = []
        for kw, w in fund_weights.items():
            if kw in title:
                fn_score += w * 1.4
                matched_fund.append(kw)
            elif kw in content:
                fn_score += w
                matched_fund.append(kw)
        if category in ["funding", "policy"]:
            fn_score += 4.0
        funding_score = min(20.0, fn_score)

        # 총점 합산 (최대 100점)
        total_score = round(keyword_score + company_score + competitor_score + funding_score, 1)
        total_score = min(100.0, max(10.0, total_score))

        return {
            "keyword_score": round(keyword_score, 1),
            "company_score": round(company_score, 1),
            "competitor_score": round(competitor_score, 1),
            "funding_score": round(funding_score, 1),
            "total_score": total_score,
            "matched_keywords": matched_kws,
            "matched_domain": matched_domain,
            "matched_competitors": matched_comp,
            "matched_funding": matched_fund
        }

    # -----------------------------------------------------------------------
    # 2. 지능형 규칙 기반 추천 이유 생성 (Rule-based Reason)
    # -----------------------------------------------------------------------
    def generate_rule_reason(self, row: Dict[str, Any], scores: Dict[str, Any]) -> str:
        """분석된 점수와 카테고리를 결합하여 NovaFactory AI 맞춤형 추천 사유 자동 생성"""
        category = row.get("category", "")
        title = row.get("title", "")
        matched_comp = scores.get("matched_competitors", [])
        matched_domain = scores.get("matched_domain", [])
        matched_fund = scores.get("matched_funding", [])

        # 경쟁사 직접 매칭
        if matched_comp:
            comp_name = matched_comp[0].upper()
            return f"[경쟁사 모니터링] 주요 경쟁사 '{comp_name}' 관련 시장 동향으로, 당사 비전 검사 SaaS 제품군과의 기술 차별점 및 고객사 수주 경쟁 전략 점검에 필수적인 정보입니다."

        # 정부 지원 / 정책
        if category in ["funding", "policy"] or scores["funding_score"] >= 12:
            reasons = []
            if "ai 바우처" in matched_fund:
                reasons.append("중소 제조기업 AI 바우처 공급기업 매칭")
            if "스마트공장" in matched_fund:
                reasons.append("스마트팩토리 보급확산 솔루션 연계")
            if "r&d" in matched_fund or "기술개발" in matched_fund:
                reasons.append("엣지 AI 비전 연구개발 정부 자금 확보")
            lead = ", ".join(reasons) if reasons else "제조업 AX 지원사업 공고"
            return f"[정부지원/사업화] {lead} 정보로, NovaFactory AI의 타깃 고객사인 중소·중견 공장의 구축 비용 부담을 경감하고 도입 계약을 가속화할 기회입니다."

        # 기술 동향
        if category == "technology" or "비전" in matched_domain or "불량" in matched_domain or "엣지 ai" in matched_domain:
            focus = []
            if any(t in matched_domain for t in ["불량", "결함", "외관"]):
                focus.append("외관 불량 탐지 정밀도 고도화")
            if any(t in matched_domain for t in ["엣지 ai", "edge ai"]):
                focus.append("공정 현장 온디바이스 엣지 AI 추론 최적화")
            if "반도체" in matched_domain or "전자부품" in matched_domain:
                focus.append("반도체/전자부품 공정 특화 비전 모델")
            lead = " 및 ".join(focus) if focus else "머신비전 품질검사 핵심 알고리즘"
            return f"[기술동향 분석] {lead} 관련 최신 데이터로, NovaFactory AI의 딥러닝 불량 검출 알고리즘 개선 및 품질 리포트 자동화 기술 로드맵에 즉각 반영할 가치가 있습니다."

        # 시장 트렌드
        if category == "market" or scores["company_score"] >= 10:
            return f"[시장 동향 파악] 제조업 AI 비전 도입 수요와 스마트팩토리 전환 흐름을 보여주는 기사로, 반도체·전자부품 제조 공정 영업 파이프라인 확장 및 시장 포지셔닝에 기여합니다."

        # 기본 일반 추천
        return f"[비즈니스 연관] 스마트 제조 및 공정 자동화 도메인 정보로, NovaFactory AI의 핵심 비즈니스 영역과 부합하며 시장 변화 대응에 유용한 인사이트를 제공합니다."

    # -----------------------------------------------------------------------
    # 3. Gemini LLM 심층 평가 (Gemini API Key 존재 시 호출)
    # -----------------------------------------------------------------------
    def evaluate_with_gemini(self, top_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gemini 2.5 Flash를 활용한 기업 관련성·사업 중요도·대응 필요성 평가 및 추천 이유 생성"""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.logger.info("GEMINI_API_KEY 미설정. 규칙 기반(Rule-based) 모드로 전환합니다.")
            return top_candidates

        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            self.logger.info("Google GenAI 클라이언트 초기화 성공. LLM 심층 평가를 시작합니다.")

            system_instruction = f"""
당신은 제조업 AI 비전 품질검사 스타트업 '{self.config.get('company_name', 'NovaFactory AI')}'의 수석 비즈니스 분석가입니다.
당사의 핵심 프로필:
- 사업 분야: {self.config.get('business_area', '제조업 AI 비전 품질검사')}
- 주요 제품: {', '.join(self.config.get('products', []))}
- 타깃 시장: {', '.join(self.config.get('target_market', []))}
- 주요 경쟁사: {', '.join(self.config.get('competitors', []))}

주어지는 기사 후보들에 대해 다음을 JSON 형식으로 평가하세요:
1. relevance_score (기업 관련성 1~10)
2. impact_score (사업 중요도 1~10)
3. action_score (대응 필요성 1~10)
4. reason (당사 관점에서 왜 중요한지와 실행 제언을 담은 1~2문장의 명확한 한국어 추천 이유)
"""

            eval_target_count = min(30, len(top_candidates))
            batch_items = []
            for i in range(eval_target_count):
                it = top_candidates[i]
                batch_items.append({
                    "id": it.get("article_id"),
                    "title": it.get("title"),
                    "category": it.get("category"),
                    "summary": it.get("summary", "")[:150]
                })

            prompt = f"{system_instruction}\n\n[평가할 기사 목록]\n{json.dumps(batch_items, ensure_ascii=False, indent=2)}\n\n반드시 각 id별 relevance_score, impact_score, action_score, reason을 포함하는 JSON 배열로만 응답하세요."

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            llm_results = json.loads(text)
            llm_map = {item["id"]: item for item in llm_results if "id" in item}

            for it in top_candidates:
                aid = it.get("article_id")
                if aid in llm_map:
                    llm_data = llm_map[aid]
                    rel = float(llm_data.get("relevance_score", 7))
                    imp = float(llm_data.get("impact_score", 7))
                    act = float(llm_data.get("action_score", 7))
                    llm_total = round((rel + imp + act) / 30.0 * 100.0, 1)

                    rule_score = float(it["total_score"])
                    it["total_score"] = round(rule_score * 0.4 + llm_total * 0.6, 1)
                    if llm_data.get("reason"):
                        it["recommendation_reason"] = f"[AI 심층분석] {llm_data['reason']}"

            self.llm_used = True
            self.logger.info(f"Gemini LLM 심층 평가 성공 완료 ({len(llm_map)}건 반영).")

        except Exception as e:
            self.logger.warning(f"Gemini LLM 호출 중 예외 발생 ({e}). 규칙 기반 추천 이유를 유지합니다.")
            self.llm_used = False

        return top_candidates

    # -----------------------------------------------------------------------
    # 4. 상위 30개 선별 및 실행
    # -----------------------------------------------------------------------
    def recommend(self, top_n: int = 30) -> List[Dict[str, Any]]:
        """전체 데이터를 점수화하여 상위 top_n(30)개 추천 및 CSV 저장"""
        self.logger.info("=========================================================")
        self.logger.info(" [Recommender] 기업 맞춤형 인텔리전스 추천 엔진 가동")
        self.logger.info(f" - 입력 파일: {self.input_file}")
        self.logger.info("=========================================================")

        if not self.input_file.exists():
            raise FileNotFoundError(f"정제 데이터 파일을 찾을 수 없습니다: {self.input_file}")

        with open(self.input_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.logger.info(f">> 정제 데이터 {len(rows)}건에 대한 다면 점수 산출 시작...")

        scored_candidates = []
        for row in rows:
            scores = self.calculate_relevance_scores(row)
            reason = self.generate_rule_reason(row, scores)

            item = dict(row)
            item["total_score"] = scores["total_score"]
            item["keyword_score"] = scores["keyword_score"]
            item["company_score"] = scores["company_score"]
            item["competitor_score"] = scores["competitor_score"]
            item["funding_score"] = scores["funding_score"]
            item["recommendation_reason"] = reason

            scored_candidates.append(item)

        # 1차 정렬 (총점 내림차순, 최신 날짜 내림차순)
        scored_candidates.sort(key=lambda x: (float(x["total_score"]), x.get("date", "")), reverse=True)

        # 상위 30개 후보 추출
        top_candidates = scored_candidates[:top_n]

        # LLM 심층 평가 적용 (API Key 존재 시)
        top_candidates = self.evaluate_with_gemini(top_candidates)

        # LLM 점수 반영 후 재정렬
        top_candidates.sort(key=lambda x: (float(x["total_score"]), x.get("date", "")), reverse=True)

        # 랭킹(rank) 부여
        for idx, it in enumerate(top_candidates, start=1):
            it["rank"] = idx

        # CSV 저장
        self.save_csv(top_candidates)

        return top_candidates

    def save_csv(self, top_candidates: List[Dict[str, Any]]) -> Path:
        """recommended_market_news.csv 저장"""
        fieldnames = [
            "rank",
            "article_id",
            "category",
            "total_score",
            "keyword_score",
            "company_score",
            "competitor_score",
            "funding_score",
            "title",
            "recommendation_reason",
            "date",
            "source_name",
            "source_url",
            "company_tag",
            "keywords",
            "data_origin"
        ]

        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for it in top_candidates:
                writer.writerow(it)

        self.logger.info(f"상위 30개 추천 CSV 저장 완료: {self.output_file} (총 {len(top_candidates)}행)")

        try:
            alt_output = None
            if "project1" in str(self.base_dir):
                alt_output = self.base_dir.parent / "data" / "processed" / "recommended_market_news.csv"
            else:
                alt_output = self.base_dir / "project1" / "data" / "processed" / "recommended_market_news.csv"

            if alt_output:
                alt_output.parent.mkdir(parents=True, exist_ok=True)
                with open(alt_output, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    for it in top_candidates:
                        writer.writerow(it)
                self.logger.info(f"보조 디렉터리 동기화 완료: {alt_output}")
        except Exception as e:
            self.logger.warning(f"보조 동기화 생략: {e}")

        return self.output_file


# ---------------------------------------------------------------------------
# CLI 엔트리포인트
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    recommender = MarketNewsRecommender()
    top30 = recommender.recommend(top_n=30)

    # 추천 결과와 웹 리포트를 한 번에 생성 (SiteBuilder 자동 연계)
    site_build_res = None
    try:
        try:
            from src.build_site import SiteBuilder
        except ImportError:
            from build_site import SiteBuilder
        builder = SiteBuilder(recommender.base_dir)
        site_build_res = builder.build()
    except Exception as e:
        recommender.logger.warning(f"웹 리포트 자동 빌드 생략: {e}")

    print("\n" + "=" * 70)
    print(" [MARKET INTELLIGENCE TOP 10 RECOMMENDATION PREVIEW]")
    print("=" * 70)
    print(f"[*] LLM 사용 여부: {'사용 (Gemini 2.5 Flash)' if recommender.llm_used else '미사용 (고급 규칙 기반 엔진 적용)'}")
    print(f"[*] 추천 대상: {recommender.config.get('company_name', 'NovaFactory AI')}")
    print(f"[*] 정적 대시보드: {site_build_res['html_path'] if site_build_res else 'docs/index.html'}")
    print(f"[*] JSON 리포트 : {site_build_res['json_path'] if site_build_res else 'docs/report.json'}")
    print("-" * 70)
    for it in top30[:10]:
        print(f"[{int(it['rank']):02d}위] ({float(it['total_score']):.1f}점 / {it['category']}) {it['title']}")
        print(f"     사유: {it['recommendation_reason']}")
        print(f"     출처: {it['source_name']} | URL: {it['source_url']}")
        print("-" * 70)
