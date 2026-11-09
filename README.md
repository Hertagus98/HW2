# ETF Backtester

FastAPI와 Plotly.js로 만든 ETF 적립식 투자 백테스터입니다. VOO, QQQ, QLD, SCHD 등을 동일한 조건으로 비교할 수 있습니다.

## 실행

Windows PowerShell에서:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000 을 엽니다.

## 계산 기준

- Yahoo Finance의 `Adj Close`를 사용합니다. 조정 종가는 일반적으로 배당 및 주식분할 효과를 반영하므로 가격 흐름을 총수익 관점으로 비교합니다.
- 초기 투자금은 요청 기간의 첫 유효 거래일에 매수합니다.
- 월 적립금은 이후 각 달의 첫 유효 거래일에 매수합니다. 매수 주식 수는 해당일 조정 종가로 나눈 금액이며, fractional share를 허용합니다.
- 평가액은 누적 보유 주식 수 × 조정 종가입니다. 누적 수익률은 평가액/누적 투자원금 - 1, 연환산 수익률은 XIRR, MDD는 납입금을 제거한 시간가중 자산곡선의 최대 하락률입니다.
- Yahoo Finance가 반환하는 첫 데이터가 요청 시작일보다 늦으면 그 날짜부터 계산하고 경고를 표시합니다. 상장 전 기간을 임의의 가격으로 채우지 않습니다.

## 성과 지표와 현금흐름

적립식 투자에서는 납입금 자체가 평가액을 키우므로 단순히 `최종 평가액 / 누적 투자원금`을 연환산하면 투자 성과가 왜곡될 수 있습니다.

- 현금흐름 반영 수익률: 각 납입금을 음수 현금흐름, 최종 평가액을 양수 현금흐름으로 두고 XIRR을 계산합니다. 산식은 `NPV(r) = Σ 현금흐름ᵢ / (1+r)^((날짜ᵢ-첫 날짜)/365.25) = 0`을 만족하는 연환산 `r`입니다.
- MDD는 종가 매수에 맞춰 일별 수익률을 `(당일 평가액 - 당일 납입금) / 전일 평가액 - 1`로 계산합니다. 이 수익률을 연결한 시간가중 곡선에서 최대 낙폭을 구합니다.
- 기존 `cagr_pct` 응답 필드는 호환성을 위해 유지하지만, 값은 이제 현금흐름을 반영한 XIRR과 같습니다. 화면에는 `현금흐름 반영 수익률`과 `납입금 제거 MDD`로 표시합니다.

계산 테스트는 `tests/test_metrics.py`에 있으며, 동일 가격 데이터와 조건에서 기존 단순 CAGR과 개선 지표를 비교할 때 납입 시점과 금액이 반영되는지 검증합니다.

## Docker

Docker Desktop이 실행 중인 상태에서 프로젝트 루트(`HW2-GitHub`)에서 실행합니다.

```powershell
docker build -t randomxssmemory/etf-backtester:latest .
docker run --rm -p 127.0.0.1:8000:8000 randomxssmemory/etf-backtester:latest
```

브라우저에서 http://127.0.0.1:8000 을 열 수 있습니다. 컨테이너 안의 FastAPI는 `0.0.0.0:8000`에서 수신합니다.

## GitHub Actions와 Docker Hub

`main` 브랜치에 push하면 `.github/workflows/ci.yml`이 `randomxssmemory/etf-backtester` 이미지를 `latest`와 커밋 SHA 태그로 Docker Hub에 push합니다.

GitHub 저장소의 **Settings → Secrets and variables → Actions**에 다음 Repository secrets를 등록합니다.

- `DOCKERHUB_USERNAME`: Docker Hub 사용자명
- `DOCKERHUB_TOKEN`: Docker Hub Access Token

```powershell
git add Dockerfile .dockerignore .github/workflows/ci.yml requirements.txt README.md
git commit -m "Add Docker build and publish workflow"
git push origin main
```

## API

`GET /api/etfs`는 지원 ETF를 반환하고, `POST /api/backtest`는 다음 JSON을 받습니다.

```json
{"tickers":["VOO","QQQ"],"initial_investment":10000000,"monthly_contribution":500000,"start_date":"2015-01-01","end_date":"2025-01-01"}
```

인터넷 연결이 필요하며, Yahoo Finance 조회 실패·잘못된 날짜·지원하지 않는 ETF는 HTTP 오류와 화면 메시지로 처리합니다.

## v1.2.0 비교 기능

- 선형/로그 축 버튼으로 자산 그래프의 Y축을 전환합니다.
- 시작일 기본값은 2000-01-01입니다. 2000/2010/2015년 빠른 선택과 직접 날짜 입력을 지원하며, 요청 기간과 각 결과의 실제 계산 기간을 함께 표시합니다. 2015년 데이터 하한은 없습니다.
- 개별 ETF는 실제 데이터가 있는 기간을 사용합니다. 일시금 또는 비중 비교를 켜면 선택 ETF의 공통 거래일만 사용합니다. 늦게 상장한 ETF를 함께 고르면 공통 시작일도 늦어집니다. 가격을 과거로 채우지 않습니다.
- 일시금은 적립식의 최종 누적 납입금과 같은 금액을 공통 시작일 종가에 전액 투자합니다. 적립식은 초기 투자 후 다음 달부터 매월 첫 거래일 종가에 매수합니다. 대기 현금 이자는 제외합니다.
- 비중 비교는 포트폴리오 A/B 각각 합계 100%를 입력합니다. 초기 투자와 각 월 납입금을 해당 비중으로 배분해 매수하고, 보유분 리밸런싱은 하지 않습니다. 전략 비교와 함께 사용할 수 있습니다.
- CSV는 모든 결과의 날짜 합집합으로 정렬하며 데이터가 없는 칸은 비워둡니다. UTF-8 BOM을 포함합니다.
- 조정 가격은 소수점 매수와 배당 재투자를 가정합니다. KRW 표시는 환율 고정 가정의 투자금 단위입니다. 실제 원/달러 환율 수익과 세금·거래비용은 제외합니다.
- 서버는 동일 ETF·기간의 성공한 가격 조회를 최대 128건 메모리 캐시합니다. 서버 재시작 시 갱신됩니다.

추가 상품의 공식 설명은 다음과 같습니다.

- [GLD](https://www.spdrgoldshares.com/usa/gld/)는 금 현물 기반 상품입니다.
- [USO](https://www.uscfinvestments.com/disclosures)는 원유 선물 기반 상품입니다.
- [SOXQ](https://www.invesco.com/us/en/financial-products/etfs/invesco-phlx-semiconductor-etf.html)는 PHLX 반도체 지수 추종 ETF입니다.
- QLD/TQQQ는 NASDAQ 100 일일 2/3배, SSO/UPRO는 S&P 500 일일 2/3배, SOXL은 반도체 일일 3배, UGL/UCO는 금/원유 선물 일일 2배 목표 상품입니다. 레버리지 상품은 실제 조정 가격을 사용하며 장기 수익률에 배수를 곱해 합성하지 않습니다. [ProShares](https://www.proshares.com/our-etfs/leveraged-and-inverse), [Direxion](https://www.direxion.com/semiconductor-etfs)

비교 요청 예시입니다.

```json
{"tickers":["QQQ","GLD"],"initial_investment":10000000,"monthly_contribution":500000,"start_date":"2005-01-01","end_date":"2024-01-01","compare_strategies":true,"portfolios":[{"name":"A","weights":{"QQQ":60,"GLD":40}},{"name":"B","weights":{"QQQ":80,"GLD":20}}]}
```
