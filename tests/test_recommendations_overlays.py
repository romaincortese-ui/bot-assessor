from bot_assessor.backtest import BacktestResult
from bot_assessor.config import BotConfig
from bot_assessor.logs import LogAnalysis
from bot_assessor.overlays import build_safe_overlays
from bot_assessor.recommendations import build_recommendations


def test_negative_backtest_prepares_safe_overlay_for_mature_bot(now_utc) -> None:
    bot = BotConfig(
        id="spot",
        name="Spot",
        github_repo="owner/repo",
        allow_parameter_overlays=True,
        allowed_overlay_types=["score_offset"],
    )
    logs = LogAnalysis(0, 0, 0, 0, 0, 0, 0, 0)
    backtest = BacktestResult(True, ["python", "bt.py"], 0, "", total_trades=12, total_pnl=-5.0)

    recommendations = build_recommendations(bot, logs, backtest)
    overlays = build_safe_overlays(bot, recommendations, generated_at=now_utc)

    assert any(item.title == "Rolling backtest is negative" for item in recommendations)
    assert overlays[0]["type"] == "score_offset"
    assert overlays[0]["source"] == "bot-assessor"


def test_research_bot_never_prepares_overlay(now_utc) -> None:
    bot = BotConfig(id="bonds", name="Bonds", github_repo="owner/repo", allow_parameter_overlays=False)
    logs = LogAnalysis(0, 0, 0, 0, 0, 0, 0, 0)
    backtest = BacktestResult(True, ["python", "bt.py"], 0, "", total_trades=12, total_pnl=-5.0)

    recommendations = build_recommendations(bot, logs, backtest)
    overlays = build_safe_overlays(bot, recommendations, generated_at=now_utc)

    assert recommendations
    assert overlays == []