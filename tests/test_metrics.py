import numpy as np
import pandas as pd

from main import simulate, xirr


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
