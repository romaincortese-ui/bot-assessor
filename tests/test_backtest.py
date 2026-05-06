from bot_assessor.backtest import parse_backtest_output


def test_parse_json_summary_backtest_output() -> None:
    parsed = parse_backtest_output('{"summary":{"total_trades":2,"total_pnl":12.5,"profit_factor":1.8,"win_rate":0.5,"max_drawdown":-0.02}}')

    assert parsed["total_trades"] == 2
    assert parsed["total_pnl"] == 12.5
    assert parsed["profit_factor"] == 1.8
    assert parsed["win_rate"] == 0.5
    assert parsed["max_drawdown"] == -0.02


def test_parse_text_backtest_output() -> None:
    parsed = parse_backtest_output("trades=3 wins=2 losses=1 win_rate=66.67%\npnl=4.20 return=1.40% pf=2.10 max_dd=-3.00%")

    assert parsed["total_trades"] == 3
    assert parsed["total_pnl"] == 4.2
    assert round(parsed["return_pct"], 6) == 0.014
    assert parsed["profit_factor"] == 2.1
    assert parsed["max_drawdown"] == -0.03