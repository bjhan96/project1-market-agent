"""
End-to-End Market Intelligence Pipeline Runner (통합 파이프라인 러너)

- 목표: 수집 -> 정제 -> 추천 -> 웹 Dashboard 생성을 원스톱으로 실행하고 실패에 유연하게 대응
- 실행 흐름:
  1. Stage 1 (Collection) : crawler.py 호출 (오류/200건 미만 시 fallback 자동 병합)
  2. Stage 2 (Cleaning)   : cleaner.py 호출 (HTML 노이즈 제거, 결측/중복 필터링, 날짜 정규화)
  3. Stage 3 (Recommend)  : recommender.py 호출 (4대 축 스코어링 + LLM/Rule 기반 추천 사유)
  4. Stage 4 (Dashboard)  : build_site.py 호출 (docs/index.html & docs/report.json 생성)
- 상태 관리: SUCCESS / WARNING / FAILED
- 로깅: logs/pipeline.log
"""

import os
import sys
import csv
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

# Windows 콘솔 출력 인코딩 안전화
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 프로젝트 내부 모듈 import 경로 설정
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# 기존 모듈 임포트 (중복 구현 없이 기존 모듈 호출)
try:
    from src.crawler import MarketNewsCrawler
    from src.cleaner import MarketNewsCleaner
    from src.recommender import MarketNewsRecommender
    from src.build_site import SiteBuilder
except ImportError:
    from crawler import MarketNewsCrawler
    from cleaner import MarketNewsCleaner
    from recommender import MarketNewsRecommender
    from build_site import SiteBuilder


# ---------------------------------------------------------------------------
# 로깅 설정 (logs/pipeline.log)
# ---------------------------------------------------------------------------
def setup_pipeline_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pipeline.log"

    logger = logging.getLogger("PipelineRunner")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 콘솔 핸들러
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # 파일 핸들러 (logs/pipeline.log)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# PipelineRunner 클래스
# ---------------------------------------------------------------------------
class PipelineRunner:
    def __init__(self, base_dir: Optional[Path] = None):
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

        self.log_dir = self.base_dir / "logs"
        self.raw_file = self.base_dir / "data" / "raw" / "crawled_market_news.csv"
        self.cleaned_file = self.base_dir / "data" / "processed" / "cleaned_market_news.csv"
        self.recommended_file = self.base_dir / "data" / "processed" / "recommended_market_news.csv"
        self.fallback_file = self.base_dir / "data" / "fallback" / "fallback_market_news.csv"
        self.html_file = self.base_dir / "docs" / "index.html"
        self.json_file = self.base_dir / "docs" / "report.json"

        self.logger = setup_pipeline_logging(self.log_dir)

        # 파이프라인 단계별 상태 기록
        self.stage_results: Dict[str, Dict[str, Any]] = {
            "1_COLLECTION": {"name": "데이터 수집 (Collection)", "status": "PENDING", "duration": 0.0, "details": ""},
            "2_CLEANING":   {"name": "데이터 정제 (Cleaning)",   "status": "PENDING", "duration": 0.0, "details": ""},
            "3_RECOMMEND":  {"name": "인텔리전스 추천 (Recommend)", "status": "PENDING", "duration": 0.0, "details": ""},
            "4_DASHBOARD":  {"name": "웹 대시보드 (Dashboard)", "status": "PENDING", "duration": 0.0, "details": ""}
        }

    # -----------------------------------------------------------------------
    # Fallback 데이터 병합 보조 메서드
    # -----------------------------------------------------------------------
    def _apply_fallback_if_needed(self, current_items: List[Dict[str, Any]], target_min: int = 200) -> Tuple[List[Dict[str, Any]], int]:
        """수집 건수가 target_min(200) 미만일 때 fallback 데이터로 안전하게 보충"""
        if len(current_items) >= target_min:
            return current_items, 0

        self.logger.warning(f"수집 건수({len(current_items)}건)가 최소 기준({target_min}건) 미달입니다. Fallback 데이터를 병합합니다.")

        fallback_items = []
        if self.fallback_file.exists():
            with open(self.fallback_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fallback_items = list(reader)

        needed = target_min - len(current_items)
        supplement = fallback_items[:needed] if len(fallback_items) >= needed else fallback_items
        for row in supplement:
            row["data_origin"] = "synthetic_fallback"
            row["collected_at"] = datetime.now().isoformat()

        merged_items = current_items + supplement
        self.logger.info(f"Fallback {len(supplement)}건 병합 완료 (최종 {len(merged_items)}건 확보).")

        # 병합 데이터 저장
        self.raw_file.parent.mkdir(parents=True, exist_ok=True)
        if merged_items:
            fieldnames = list(merged_items[0].keys())
            with open(self.raw_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for r in merged_items:
                    writer.writerow(r)

        return merged_items, len(supplement)

    # -----------------------------------------------------------------------
    # Stage 1: 수집 (Collection)
    # -----------------------------------------------------------------------
    def run_stage_collection(self) -> bool:
        start_t = time.time()
        stage_key = "1_COLLECTION"
        self.logger.info("\n" + "=" * 65)
        self.logger.info(" [STAGE 1] 데이터 수집 (Collection) 시작")
        self.logger.info("=" * 65)

        status = "SUCCESS"
        details = ""

        try:
            crawler = MarketNewsCrawler(base_dir=self.base_dir)
            # Timeout, 403, RSS 오류 등에도 crawler 내부 예외 처리로 안전 수집
            crawl_res = crawler.run()

            total_count = crawl_res.get("total_count", 0)
            live_count = crawl_res.get("live_count", 0)
            fallback_count = crawl_res.get("fallback_count", 0)
            failed_sources = crawl_res.get("failed_sources", [])

            # 200건 미만 검사 및 보충
            if total_count < 200:
                self.logger.warning(f"수집 결과({total_count}건)가 200건 미달입니다. 파이프라인 레벨에서 Fallback 추가 병합.")
                current_items = crawler.collected_items
                merged, added = self._apply_fallback_if_needed(current_items, target_min=200)
                total_count = len(merged)
                fallback_count += added
                status = "WARNING"

            if fallback_count > 0 or failed_sources:
                status = "WARNING"
                details = f"총 {total_count}건 (라이브: {live_count}건, Fallback: {fallback_count}건, 실패 Source: {len(failed_sources)}개)"
            else:
                status = "SUCCESS"
                details = f"라이브 공개 Source {total_count}건 전원 정상 수집 (목표 200건 달성, 실패: 0개)"

        except Exception as e:
            self.logger.error(f"수집 단계 중 예외 발생: {e}. Fallback 데이터셋으로 전면 복구합니다.")
            merged, added = self._apply_fallback_if_needed([], target_min=200)
            status = "WARNING" if len(merged) >= 200 else "FAILED"
            details = f"수집 실패로 Fallback {added}건 긴급 복구 적용 ({e})"

        duration = time.time() - start_t
        self.stage_results[stage_key]["status"] = status
        self.stage_results[stage_key]["duration"] = round(duration, 2)
        self.stage_results[stage_key]["details"] = details
        self.logger.info(f"[{status}] Stage 1 완료 ({duration:.2f}s) - {details}")
        return status != "FAILED"

    # -----------------------------------------------------------------------
    # Stage 2: 정제 (Cleaning)
    # -----------------------------------------------------------------------
    def run_stage_cleaning(self) -> bool:
        start_t = time.time()
        stage_key = "2_CLEANING"
        self.logger.info("\n" + "=" * 65)
        self.logger.info(" [STAGE 2] 데이터 정제 및 품질 검증 (Cleaning) 시작")
        self.logger.info("=" * 65)

        status = "SUCCESS"
        details = ""

        try:
            cleaner = MarketNewsCleaner(base_dir=self.base_dir)
            clean_res = cleaner.run()

            cleaned_cnt = clean_res.get("cleaned_count", 0)
            dup_cnt = clean_res.get("duplicates_removed", 0)
            inv_cnt = clean_res.get("invalid_missing_removed", 0)
            is_verified = clean_res.get("verification", {}).get("passed", False)

            if cleaned_cnt < 200 or not is_verified:
                status = "WARNING"
                details = f"정제 {cleaned_cnt}건 (중복 제거: {dup_cnt}건, 결측 제거: {inv_cnt}건, 검증: {'PASS' if is_verified else 'CHECK'})"
            else:
                details = f"정제 {cleaned_cnt}건 완료 (중복 {dup_cnt}건 제거, 결측 0건, 무결성 검증 통과)"

        except Exception as e:
            self.logger.error(f"정제 단계 실패: {e}")
            status = "FAILED"
            details = f"정제 오류 발생: {e}"

        duration = time.time() - start_t
        self.stage_results[stage_key]["status"] = status
        self.stage_results[stage_key]["duration"] = round(duration, 2)
        self.stage_results[stage_key]["details"] = details
        self.logger.info(f"[{status}] Stage 2 완료 ({duration:.2f}s) - {details}")
        return status != "FAILED"

    # -----------------------------------------------------------------------
    # Stage 3: 추천 (Recommend)
    # -----------------------------------------------------------------------
    def run_stage_recommend(self) -> bool:
        start_t = time.time()
        stage_key = "3_RECOMMEND"
        self.logger.info("\n" + "=" * 65)
        self.logger.info(" [STAGE 3] 기업 맞춤형 인텔리전스 추천 (Recommend) 시작")
        self.logger.info("=" * 65)

        status = "SUCCESS"
        details = ""

        try:
            recommender = MarketNewsRecommender(base_dir=self.base_dir)
            top30 = recommender.recommend(top_n=30)

            if len(top30) < 30:
                status = "WARNING"
                details = f"추천 {len(top30)}건 선별 (목표 30건 미달)"
            else:
                engine = "Gemini 2.5 Flash LLM" if recommender.llm_used else "규칙 기반 다면 엔진"
                status = "SUCCESS" if recommender.llm_used else "WARNING"
                details = f"상위 30건 엄선 완료 ({engine} 적용, 최고 {top30[0]['total_score']}점)"

        except Exception as e:
            self.logger.error(f"추천 단계 실패: {e}")
            status = "FAILED"
            details = f"추천 알고리즘 오류 발생: {e}"

        duration = time.time() - start_t
        self.stage_results[stage_key]["status"] = status
        self.stage_results[stage_key]["duration"] = round(duration, 2)
        self.stage_results[stage_key]["details"] = details
        self.logger.info(f"[{status}] Stage 3 완료 ({duration:.2f}s) - {details}")
        return status != "FAILED"

    # -----------------------------------------------------------------------
    # Stage 4: 대시보드 (Dashboard)
    # -----------------------------------------------------------------------
    def run_stage_dashboard(self) -> bool:
        start_t = time.time()
        stage_key = "4_DASHBOARD"
        self.logger.info("\n" + "=" * 65)
        self.logger.info(" [STAGE 4] 정적 웹 대시보드 및 리포트 빌드 (Dashboard) 시작")
        self.logger.info("=" * 65)

        status = "SUCCESS"
        details = ""

        try:
            builder = SiteBuilder(base_dir=self.base_dir)
            site_res = builder.build()

            html_exists = Path(site_res["html_path"]).exists()
            json_exists = Path(site_res["json_path"]).exists()

            if html_exists and json_exists:
                details = f"docs/index.html & docs/report.json 생성 완료 (추천 {site_res['total_recommended']}건 렌더링)"
            else:
                status = "WARNING"
                details = "일부 웹 산출물 파일 미생성"

        except Exception as e:
            self.logger.error(f"대시보드 빌드 실패: {e}")
            status = "FAILED"
            details = f"대시보드 빌더 오류 발생: {e}"

        duration = time.time() - start_t
        self.stage_results[stage_key]["status"] = status
        self.stage_results[stage_key]["duration"] = round(duration, 2)
        self.stage_results[stage_key]["details"] = details
        self.logger.info(f"[{status}] Stage 4 완료 ({duration:.2f}s) - {details}")
        return status != "FAILED"

    # -----------------------------------------------------------------------
    # 전체 파이프라인 총괄 실행
    # -----------------------------------------------------------------------
    def run(self) -> bool:
        total_start_t = time.time()
        self.logger.info("#################################################################")
        self.logger.info(" [PIPELINE] Market Intelligence Agent 통합 파이프라인 가동")
        self.logger.info(f" - 기준 경로: {self.base_dir}")
        self.logger.info("#################################################################")

        # 1. 수집
        s1_ok = self.run_stage_collection()

        # 2. 정제
        s2_ok = self.run_stage_cleaning() if s1_ok else False

        # 3. 추천
        s3_ok = self.run_stage_recommend() if s2_ok else False

        # 4. 웹 대시보드
        s4_ok = self.run_stage_dashboard() if s3_ok else False

        total_duration = time.time() - total_start_t
        overall_status = "SUCCESS" if (s1_ok and s2_ok and s3_ok and s4_ok) else "FAILED"

        # 최종 요약 출력 및 로깅
        self.print_summary(total_duration, overall_status)

        return overall_status == "SUCCESS"

    def print_summary(self, total_duration: float, overall_status: str):
        summary_lines = [
            "\n" + "=" * 75,
            " [PIPELINE EXECUTION SUMMARY REPORT (종합 실행 보고서)]",
            "=" * 75,
            f"[*] 전체 소요 시간 : {total_duration:.2f}초",
            f"[*] 최종 파이프라인 : {'성공 (COMPLETED)' if overall_status == 'SUCCESS' else '실패 (FAILED)'}",
            "-" * 75,
            f"{'단계 (Stage)':<30} | {'상태 (Status)':<10} | {'소요시간':<8} | {'상세 내용'}",
            "-" * 75,
        ]

        for k, v in self.stage_results.items():
            status_str = f"[{v['status']}]"
            line = f"{v['name']:<28} | {status_str:<10} | {v['duration']:>6.2f}s | {v['details']}"
            summary_lines.append(line)

        summary_lines.extend([
            "-" * 75,
            "[*] 생성된 핵심 산출물 (Artifacts):",
            f" 1. 원본 데이터 : {self.raw_file} ({self._get_line_count(self.raw_file)}행)",
            f" 2. 정제 데이터 : {self.cleaned_file} ({self._get_line_count(self.cleaned_file)}행)",
            f" 3. 추천 데이터 : {self.recommended_file} ({self._get_line_count(self.recommended_file)}행)",
            f" 4. 웹 대시보드 : {self.html_file} ({'존재' if self.html_file.exists() else '없음'})",
            f" 5. JSON 리포트 : {self.json_file} ({'존재' if self.json_file.exists() else '없음'})",
            f" 6. 실행 로그   : {self.log_dir / 'pipeline.log'}",
            "=" * 75
        ])

        summary_text = "\n".join(summary_lines)
        self.logger.info(summary_text)

    def _get_line_count(self, file_path: Path) -> int:
        if not file_path.exists():
            return 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return max(0, sum(1 for _ in f) - 1)
        except Exception:
            return 0


# ---------------------------------------------------------------------------
# CLI 엔트리포인트
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    runner = PipelineRunner()
    success = runner.run()
    sys.exit(0 if success else 1)
