# Project 1: Market Agent (시장/경쟁사 분석 에이전트)

`project1-market-agent`는 특정 기업의 프로필(`config/company_profile.yaml`)을 기반으로 시장 트렌드, 기술 동향, 경쟁사 소식, 정부 지원사업/펀딩 정보를 자동으로 수집하고 분석하는 지능형 에이전트 프로젝트입니다.

---

## 1. 프로젝트 구조

```text
project1/
├── .github/
│   └── workflows/          # CI/CD 워크플로우 정의
├── config/
│   └── company_profile.yaml # 분석 대상 기업 프로필, 경쟁사 및 키워드 설정
├── data/
│   ├── fallback/           # 웹 수집 실패 또는 예비용 합성 데이터
│   │   └── fallback_market_news.csv
│   ├── raw/                # 수집된 원본 데이터 저장소
│   └── processed/          # 정제 및 가공 완료된 데이터
├── docs/                   # 프로젝트 문서 및 설계서
├── logs/                   # 실행 로그
├── src/                    # 에이전트 소스 코드 패키지
│   └── __init__.py
├── .env.example            # 환경 변수 예시 템플릿
├── .gitignore              # Git 무시 파일 목록
├── requirements.txt        # 프로젝트 의존성 패키지 목록
└── README.md               # 프로젝트 개요 및 안내 문서
```

---

## 2. 기업 프로필 및 수집 기준 설정 (`config/company_profile.yaml`)

- **기업명**: NovaFactory AI
- **사업 분야**: 제조업 AI 비전 품질검사
- **주요 제품**:
  - 비전 기반 불량 탐지 SaaS
  - 제조 품질 리포트 자동화
  - 엣지 AI 품질 분석 솔루션
- **타깃 시장**:
  - 중소·중견 제조기업
  - 스마트팩토리 구축 기업
  - 반도체/전자부품 외관 검사 공정
- **경쟁사 모니터링 대상 (4개)**:
  - VisionForge
  - InspectAI
  - FactoryMind
  - QualiBot
- **관심 키워드 (8개)**:
  - AI, 스마트팩토리, 품질검사, 자동화, 클라우드, 제조 AX, 디지털 전환, 머신비전
- **지원사업/펀딩 키워드 (6개)**:
  - 창업지원, AI 바우처, 스마트공장, R&D, 사업화 자금, 중소기업 지원

---

## 3. 데이터 운영 가이드

- **Fallback 데이터**: `data/fallback/fallback_market_news.csv` (총 800행의 합성 시장 뉴스 데이터)
  - 웹 크롤링/RSS 수집 실패나 네트워크 장애 발생 시 안정적인 실습과 테스트를 위한 대체 데이터셋으로 활용됩니다.
  - 카테고리 구성: `policy`, `technology`, `competitor`, `market`, `funding`

---

## 4. 환경 설정 및 실행 방법

```bash
# 1. 의존성 패키지 설치
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env 파일에 GEMINI_API_KEY 설정 (필요시)
```
