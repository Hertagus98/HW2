from datetime import date, datetime
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="ETF Backtester", version="1.1.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

SUPPORTED_ETFS = ["VOO", "QQQ", "QLD", "SCHD", "SPY", "VTI", "IWM", "BND"]


class BacktestRequest(BaseModel):
    tickers: List[str] = Field(min_length=1, max_length=6)
    initial_investment: float = Field(gt=0, le=100_000_000)
    monthly_contribution: float = Field(ge=0, le=100_000_000)
    start_date: date
    end_date: date

    @field_validator("tickers")
    @classmethod
    def clean_tickers(cls, values):
        values = list(dict.fromkeys(v.strip().upper() for v in values))
        if not values or any(v not in SUPPORTED_ETFS for v in values):
            raise ValueError(f"지원 ETF: {', '.join(SUPPORTED_ETFS)}")
        return values

    @field_validator("end_date")
    @classmethod
    def valid_dates(cls, value, info):
        start = info.data.get("start_date")
        if start and value <= start:
            raise ValueError("종료일은 시작일보다 늦어야 합니다.")
        if start and (value - start).days > 365 * 50:
            raise ValueError("최대 백테스트 기간은 50년입니다.")
        return value


def load_prices(ticker: str, start: date, end: date) -> pd.Series:
    try:
        raw = yf.download(
            ticker, start=start.isoformat(), end=(pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat(),
            auto_adjust=False, progress=False, threads=False
        )
        if raw.empty:
            raise ValueError("가격 데이터가 없습니다.")
        prices = raw["Adj Close"] if "Adj Close" in raw else raw["Close"]
        if isinstance(prices, pd.DataFrame):
            prices = prices.iloc[:, 0]
        prices = pd.to_numeric(prices, errors="coerce").dropna()
        prices.index = pd.to_datetime(prices.index).tz_localize(None)
        if prices.empty:
            raise ValueError("유효한 조정 종가가 없습니다.")
        return prices
    except Exception as exc:
        raise ValueError(f"{ticker} 데이터를 조회하지 못했습니다: {exc}") from exc


def xnpv(rate: float, cashflows: list[tuple[pd.Timestamp, float]]) -> float:
    origin = cashflows[0][0]
    return sum(amount / (1 + rate) ** (((when - origin).days) / 365.25) for when, amount in cashflows)


def xirr(cashflows: list[tuple[pd.Timestamp, float]]) -> float:
    """Annualized money-weighted return for dated external cash flows."""
    if not any(amount < 0 for _, amount in cashflows) or not any(amount > 0 for _, amount in cashflows):
        return 0.0
    low, high = -0.999999, 10.0
    low_value, high_value = xnpv(low, cashflows), xnpv(high, cashflows)
    for _ in range(100):
        if low_value * high_value <= 0:
            break
        high *= 2
        high_value = xnpv(high, cashflows)
    else:
        return 0.0
    for _ in range(100):
        mid = (low + high) / 2
        value = xnpv(mid, cashflows)
        if abs(value) < 1e-8:
            return mid
        if low_value * value <= 0:
            high, high_value = mid, value
        else:
            low, low_value = mid, value
    return (low + high) / 2


def simulate(ticker: str, prices: pd.Series, initial: float, monthly: float) -> dict:
    start, end = prices.index[0], prices.index[-1]
    contribution_dates = [start]
    cursor = start.to_period("M") + 1
    while cursor.to_timestamp() <= end:
        eligible = prices[prices.index >= cursor.to_timestamp()]
        if not eligible.empty:
            contribution_dates.append(eligible.index[0])
        cursor += 1
    contribution_dates = sorted(set(contribution_dates))
    contributions = pd.Series(0.0, index=prices.index)
    contributions.loc[contribution_dates[0]] = initial
    for dt in contribution_dates[1:]:
        contributions.loc[dt] += monthly
    shares = (contributions / prices).cumsum()
    values = shares * prices
    invested = contributions.cumsum()
    # Remove external deposits from each period's return before calculating MDD.
    adjusted_values = pd.Series(index=prices.index, dtype=float)
    adjusted_values.iloc[0] = values.iloc[0]
    for index in range(1, len(values)):
        prior_value = values.iloc[index - 1]
        contribution = contributions.iloc[index]
        adjusted_values.iloc[index] = adjusted_values.iloc[index - 1] * values.iloc[index] / max(prior_value + contribution, 1e-12)
    peak = adjusted_values.cummax()
    drawdown = adjusted_values / peak - 1
    total_invested = float(invested.iloc[-1])
    final_value = float(values.iloc[-1])
    days = max((values.index[-1] - values.index[0]).days, 1)
    cashflows = [(pd.Timestamp(dt), -float(amount)) for dt, amount in contributions.items() if amount]
    cashflows.append((pd.Timestamp(prices.index[-1]), final_value))
    money_weighted_return = xirr(cashflows)
    return {
        "ticker": ticker, "dates": [d.strftime("%Y-%m-%d") for d in values.index],
        "value": values.round(2).tolist(), "invested": invested.round(2).tolist(),
        "total_invested": round(total_invested, 2), "final_value": round(final_value, 2),
        "return_pct": round((final_value / total_invested - 1) * 100, 2) if total_invested else 0,
        "cagr_pct": round(money_weighted_return * 100, 2),
        "money_weighted_return_pct": round(money_weighted_return * 100, 2),
        "mdd_pct": round(float(drawdown.min()) * 100, 2),
        "purchases": len(contribution_dates), "first_price_date": start.strftime("%Y-%m-%d"),
    }


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/etfs")
def etfs():
    return {"etfs": SUPPORTED_ETFS}


@app.get("/api/version")
def version():
    return {"service": "etf-backtester", "version": app.version}


@app.post("/api/backtest")
def backtest(payload: BacktestRequest):
    results = []
    errors = []
    for ticker in payload.tickers:
        try:
            prices = load_prices(ticker, payload.start_date, payload.end_date)
            if prices.index[0].date() > payload.start_date:
                errors.append(f"{ticker}: 요청 시작일 이전 데이터가 없어 {prices.index[0].date()}부터 계산했습니다.")
            results.append(simulate(ticker, prices, payload.initial_investment, payload.monthly_contribution))
        except ValueError as exc:
            errors.append(str(exc))
    if not results:
        raise HTTPException(status_code=422, detail="; ".join(errors) or "백테스트를 실행할 수 없습니다.")
    return {"results": results, "warnings": errors, "method": "Adj Close; first available trading day of each month"}
