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
- 평가액은 누적 보유 주식 수 × 조정 종가입니다. 누적 수익률은 평가액/누적 투자원금 - 1, CAGR은 실제 경과일 기준 연환산, MDD는 평가액의 고점 대비 최대 하락률입니다.
- Yahoo Finance가 반환하는 첫 데이터가 요청 시작일보다 늦으면 그 날짜부터 계산하고 경고를 표시합니다. 상장 전 기간을 임의의 가격으로 채우지 않습니다.

## 성과 지표와 현금흐름

적립식 투자에서는 납입금 자체가 평가액을 키우므로 단순히 `최종 평가액 / 누적 투자원금`을 연환산하면 투자 성과가 왜곡될 수 있습니다.

- 현금흐름 반영 수익률: 각 납입금을 음수 현금흐름, 최종 평가액을 양수 현금흐름으로 두고 XIRR을 계산합니다. 산식은 `NPV(r) = Σ 현금흐름ᵢ / (1+r)^((날짜ᵢ-첫 날짜)/365.25) = 0`을 만족하는 연환산 `r`입니다.
- MDD: 각 날짜의 납입금을 직전 평가액에 더한 뒤 기간 수익률을 계산하고, 납입금으로 인한 자산 증가를 제거한 시간가중 자산곡선에서 고점 대비 최대 하락률을 계산합니다.
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
