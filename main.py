from datetime import date
from pathlib import Path
from typing import List
from functools import lru_cache

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="ETF Backtester", version="1.2.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

ETF_DETAILS = {
    "VOO": "S&P 500", "QQQ": "NASDAQ 100", "QLD": "NASDAQ 100 일일 2배",
    "SCHD": "미국 배당주", "SPY": "S&P 500", "VTI": "미국 전체 주식",
    "IWM": "미국 소형주", "BND": "미국 종합채권", "GLD": "금 현물 기반",
    "USO": "WTI 원유 선물", "SOXQ": "PHLX 필라델피아 반도체 지수",
    "TQQQ": "NASDAQ 100 일일 3배", "SSO": "S&P 500 일일 2배",
    "UPRO": "S&P 500 일일 3배", "SOXL": "반도체 일일 3배 (NYSE 지수)",
    "UGL": "금 선물 일일 2배", "UCO": "원유 선물 일일 2배",
}
SUPPORTED_ETFS = list(ETF_DETAILS)


class Portfolio(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    weights: dict[str, float]

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, weights):
        if not weights or any(t not in SUPPORTED_ETFS for t in weights):
            raise ValueError("지원하는 ETF로 비중을 설정하세요.")
        if any(not np.isfinite(w) or w < 0 or w > 100 for w in weights.values()):
            raise ValueError("비중은 0~100 사이여야 합니다.")
        if not np.isclose(sum(weights.values()), 100, atol=0.001, rtol=0):
            raise ValueError("포트폴리오 비중 합계는 100%여야 합니다.")
        return {t: w for t, w in weights.items() if w > 0}


class BacktestRequest(BaseModel):
    tickers: List[str] = Field(min_length=1, max_length=6)
    initial_investment: float = Field(gt=0, le=100_000_000)
    monthly_contribution: float = Field(ge=0, le=100_000_000)
    start_date: date
    end_date: date
    compare_strategies: bool = False
    portfolios: list[Portfolio] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_portfolios(self):
        if any(t not in self.tickers for p in self.portfolios for t in p.weights):
            raise ValueError("비중에 포함한 ETF를 모두 선택하세요.")
        if len({p.name for p in self.portfolios}) != len(self.portfolios):
            raise ValueError("포트폴리오 이름은 서로 달라야 합니다.")
        return self

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


@lru_cache(maxsize=128)
def load_prices(ticker: str, start: date, end: date) -> pd.Series:
    try:
        raw = yf.download(
            ticker, start=start.isoformat(), end=(pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat(),
            auto_adjust=False, progress=False, threads=False
        )
        if raw.empty:
            raise ValueError("가격 데이터가 없습니다.")
        if "Adj Close" not in raw:
            raise ValueError("조정 종가가 없습니다.")
        prices = raw["Adj Close"]
        if isinstance(prices, pd.DataFrame):
            prices = prices.iloc[:, 0]
        prices = pd.to_numeric(prices, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        prices = prices[prices > 0].sort_index()
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


def simulate(ticker: str, prices: pd.Series | pd.DataFrame, initial: float, monthly: float,
             weights: dict[str, float] | None = None) -> dict:
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
    if isinstance(prices, pd.DataFrame):
        allocation = pd.Series(weights).reindex(prices.columns) / 100
        purchases = pd.DataFrame({t: contributions * allocation[t] / prices[t] for t in prices})
        values = (purchases.cumsum() * prices).sum(axis=1)
    else:
        shares = (contributions / prices).cumsum()
        values = shares * prices
    invested = contributions.cumsum()
    # Remove external deposits from each period's return before calculating MDD.
    adjusted_values = pd.Series(index=prices.index, dtype=float)
    adjusted_values.iloc[0] = values.iloc[0]
    for index in range(1, len(values)):
        prior_value = values.iloc[index - 1]
        contribution = contributions.iloc[index]
        adjusted_values.iloc[index] = adjusted_values.iloc[index - 1] * (values.iloc[index] - contribution) / max(prior_value, 1e-12)
    peak = adjusted_values.cummax()
    drawdown = adjusted_values / peak - 1
    total_invested = float(invested.iloc[-1])
    final_value = float(values.iloc[-1])
    days = max((values.index[-1] - values.index[0]).days, 1)
    cashflows = [(pd.Timestamp(dt), -float(amount)) for dt, amount in contributions.items() if amount]
    cashflows.append((pd.Timestamp(prices.index[-1]), final_value))
    money_weighted_return = xirr(cashflows) if start < end else 0.0
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
    return {"etfs": SUPPORTED_ETFS, "details": ETF_DETAILS}


@app.get("/api/version")
def version():
    return {"service": "etf-backtester", "version": app.version}


@app.post("/api/backtest")
def backtest(payload: BacktestRequest):
    results = []
    errors = []
    loaded = {}
    for ticker in payload.tickers:
        try:
            prices = load_prices(ticker, payload.start_date, payload.end_date)
            loaded[ticker] = prices
            if (prices.index[0].date() - payload.start_date).days > 7:
                errors.append(f"{ticker}: 요청 시작일부터 데이터가 없어 실제 첫 데이터 {prices.index[0].date()}부터 가능합니다. 상장 전 데이터를 채우지 않습니다.")
        except ValueError as exc:
            errors.append(str(exc))
    if not loaded:
        raise HTTPException(status_code=422, detail="; ".join(errors) or "백테스트를 실행할 수 없습니다.")
    if payload.compare_strategies or payload.portfolios:
        if len(loaded) != len(payload.tickers):
            raise HTTPException(status_code=422, detail="동일 조건 비교에 필요한 ETF 조회 실패. " + "; ".join(errors))
        common = pd.concat(loaded, axis=1).dropna()
        if len(common) < 2:
            raise HTTPException(status_code=422, detail="선택 ETF의 공통 거래 기간이 부족합니다.")
        loaded = {t: common[t] for t in loaded}
        errors.append(f"동일 조건 비교를 위해 공통 거래 기간 {common.index[0].date()} ~ {common.index[-1].date()}을 사용합니다.")

    targets = [(t, prices, None) for t, prices in loaded.items()]
    if payload.portfolios:
        targets = [(p.name, pd.DataFrame({t: loaded[t] for t in p.weights}), p.weights) for p in payload.portfolios]
    for label, prices, weights in targets:
        regular = simulate(label, prices, payload.initial_investment, payload.monthly_contribution, weights)
        regular.update(label=f"{label} · 적립식", strategy="dca", weights=weights)
        results.append(regular)
        if payload.compare_strategies:
            lump = simulate(label, prices, regular["total_invested"], 0, weights)
            lump.update(label=f"{label} · 일시금", strategy="lump_sum", weights=weights)
            results.append(lump)
    return {
        "results": results, "warnings": errors,
        "requested_start": payload.start_date.isoformat(), "requested_end": payload.end_date.isoformat(),
        "method": "Adj Close; closing-price purchases; monthly first trading day; fractional shares; no rebalancing",
    }
