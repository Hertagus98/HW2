import numpy as np
import pandas as pd
import pytest
from datetime import date

import main
from main import BacktestRequest, Portfolio, backtest, simulate, xirr


def test_xirr_is_zero_when_final_value_matches_dated_cashflows():
    dates = pd.to_datetime(["2020-01-01", "2021-01-01"])
    assert abs(xirr([(dates[0], -100.0), (dates[1], 100.0)])) < 1e-6


def test_simulate_accounts_for_monthly_cashflows_and_exposes_adjusted_metrics():
    dates = pd.date_range("2020-01-01", periods=13, freq="MS")
    prices = pd.Series(np.full(len(dates), 100.0), index=dates)
    result = simulate("TEST", prices, initial=100.0, monthly=100.0)

    assert result["total_invested"] == 1300.0
    assert result["final_value"] == 1300.0
    assert abs(result["money_weighted_return_pct"]) < 0.01
    assert result["mdd_pct"] == 0.0


def test_mdd_ignores_deposit_only_growth():
    dates = pd.date_range("2020-01-01", periods=3, freq="MS")
    prices = pd.Series([100.0, 100.0, 90.0], index=dates)
    result = simulate("TEST", prices, initial=100.0, monthly=100.0)

    assert result["mdd_pct"] < 0
    assert result["mdd_pct"] > -11


def test_close_purchase_does_not_dilute_market_drawdown():
    prices = pd.Series([100.0, 50.0], index=pd.to_datetime(["2020-01-02", "2020-02-03"]))
    assert simulate("TEST", prices, 100, 10000)["mdd_pct"] == -50.0


def test_portfolio_allocates_each_deposit_without_rebalancing():
    prices = pd.DataFrame({"VOO": [100.0, 200.0], "GLD": [100.0, 100.0]},
                          index=pd.to_datetime(["2020-01-02", "2020-02-03"]))
    result = simulate("A", prices, 100, 100, {"VOO": 60, "GLD": 40})
    assert result["value"] == [100, 260]
    assert result["total_invested"] == 200


def test_invalid_portfolio_weights_are_rejected():
    with pytest.raises(ValueError):
        Portfolio(name="A", weights={"VOO": 60, "GLD": 30})
    with pytest.raises(ValueError):
        Portfolio(name="A", weights={"VOO": float("nan")})


def test_requested_pre_2015_dates_reach_price_loader(monkeypatch):
    calls = []

    def fake_prices(ticker, start, end):
        calls.append((ticker, start, end))
        return pd.Series([100.0, 110.0, 120.0], index=pd.to_datetime(["2005-01-03", "2005-02-01", "2005-03-01"]))

    monkeypatch.setattr(main, "load_prices", fake_prices)
    payload = BacktestRequest(tickers=["QQQ"], initial_investment=100, monthly_contribution=10,
                              start_date="2005-01-01", end_date="2005-03-02", compare_strategies=True)
    result = backtest(payload)
    assert calls[0][1] == date(2005, 1, 1)
    assert result["results"][0]["dates"][0] == "2005-01-03"
    assert result["results"][0]["total_invested"] == result["results"][1]["total_invested"]
    assert result["results"][1]["invested"][0] == 120


def test_comparisons_use_common_dates_without_backfilling(monkeypatch):
    series = {
        "QQQ": pd.Series([100.0, 110.0, 120.0], index=pd.to_datetime(["2005-01-03", "2005-02-01", "2005-03-01"])),
        "GLD": pd.Series([50.0, 60.0], index=pd.to_datetime(["2005-02-01", "2005-03-01"])),
    }
    monkeypatch.setattr(main, "load_prices", lambda ticker, start, end: series[ticker])
    payload = BacktestRequest(tickers=["QQQ", "GLD"], initial_investment=100, monthly_contribution=10,
                              start_date="2005-01-01", end_date="2005-03-02", compare_strategies=True)
    result = backtest(payload)
    assert all(r["dates"] == ["2005-02-01", "2005-03-01"] for r in result["results"])
