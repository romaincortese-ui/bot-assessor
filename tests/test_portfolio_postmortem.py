from bot_assessor.backtest import BacktestResult
from bot_assessor.config import BotConfig
from bot_assessor.logs import LogAnalysis
from bot_assessor.portfolio import build_portfolio_summary, fleet_rollup
from bot_assessor.postmortem import build_postmortem


def test_portfolio_summary_normalizes_live_risk_and_decision() -> None:
    bot = BotConfig(id="indices", name="Indices Bot", github_repo="owner/indices")
    logs = LogAnalysis(0, 0, 0, 0, 0, 0, 0, 0)
    backtest = BacktestResult(True, ["python", "bt.py"], 0, "", total_trades=8, total_pnl=12.0, profit_factor=1.7, max_drawdown=-0.03)
    runtime_status = {
        "payloads": {
            "redis:state": {
                "account_nav": 1000.0,
                "open_positions": [
                    {"entry_price": 5000.0, "stop_price": 4975.0, "units": 2, "margin_used": 100.0, "unrealized_pl": 5.0},
                ],
            }
        }
    }

    summary = build_portfolio_summary(bot, logs=logs, backtest=backtest, runtime_status=runtime_status)

    assert summary.currency == "GBP"
    assert summary.live_pnl_amount == 5.0
    assert summary.risk_at_stop == 50.0
    assert summary.risk_at_stop_pct_nav == 5.0
    assert summary.decision == "hold_or_test_incremental_improvements"


def test_postmortem_turns_negative_backtest_into_hypothesis() -> None:
    bot = BotConfig(id="commodities", name="Commodities Bot", github_repo="owner/commodities")
    logs = LogAnalysis(1, 0, 0, 0, 0, 0, 0, 0, top_blockers=[("score_threshold", 4)])
    backtest = BacktestResult(True, ["python", "bt.py"], 0, "", total_trades=5, total_pnl=-3.0, profit_factor=0.8, max_drawdown=-0.05)
    portfolio = build_portfolio_summary(bot, logs=logs, backtest=backtest, runtime_status={"payloads": {}})

    postmortem = build_postmortem(bot, logs=logs, backtest=backtest, portfolio=portfolio)

    assert postmortem.severity == "high"
    assert any(item.cause == "Negative rolling expectancy" for item in postmortem.findings)
    assert any(item["change_type"] == "strategy_gate" for item in postmortem.improvement_hypotheses)


def test_fleet_rollup_groups_live_metrics_by_currency() -> None:
    rollup = fleet_rollup(
        [
            {"bot_name": "A", "portfolio": {"currency": "GBP", "live_pnl_amount": 1.0, "risk_at_stop": 2.0, "margin_used": 3.0, "backtest_pnl": 4.0, "state": "healthy"}},
            {"bot_name": "B", "portfolio": {"currency": "GBP", "live_pnl_amount": -2.0, "risk_at_stop": 5.0, "margin_used": 7.0, "backtest_pnl": -1.0, "state": "attention"}},
        ]
    )

    assert rollup["by_currency"]["GBP"]["live_pnl_amount"] == -1.0
    assert rollup["by_currency"]["GBP"]["risk_at_stop"] == 7.0
    assert rollup["attention"] == ["B"]