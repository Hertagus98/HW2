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
app = FastAPI(title="ETF Backtester", version="1.0.0")
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
    peak = values.cummax()
    drawdown = values / peak - 1
    total_invested = float(invested.iloc[-1])
    final_value = float(values.iloc[-1])
    days = max((values.index[-1] - values.index[0]).days, 1)
    cagr = (final_value / total_invested) ** (365.25 / days) - 1 if total_invested else 0
    return {
        "ticker": ticker, "dates": [d.strftime("%Y-%m-%d") for d in values.index],
        "value": values.round(2).tolist(), "invested": invested.round(2).tolist(),
        "total_invested": round(total_invested, 2), "final_value": round(final_value, 2),
        "return_pct": round((final_value / total_invested - 1) * 100, 2) if total_invested else 0,
        "cagr_pct": round(cagr * 100, 2), "mdd_pct": round(float(drawdown.min()) * 100, 2),
        "purchases": len(contribution_dates), "first_price_date": start.strftime("%Y-%m-%d"),
    }


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/etfs")
def etfs():
    return {"etfs": SUPPORTED_ETFS}


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
