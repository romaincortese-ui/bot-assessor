from bot_assessor.backtest import BacktestResult
from bot_assessor.config import BotConfig
from bot_assessor.logs import LogAnalysis
from bot_assessor.overlays import build_safe_overlays
from bot_assessor.recommendations import build_recommendations
from bot_assessor.runtime_status import RuntimeStatusCollector
from bot_assessor.variables import build_railway_variable_plan


def test_runtime_status_reads_configured_files(tmp_path) -> None:
    status_file = tmp_path / "state.json"
    status_file.write_text('{"skip_reason":"no_signal","open_positions":0}', encoding="utf-8")
    bot = BotConfig(id="bot", name="Bot", github_repo="owner/bot", runtime_status_files=["state.json"])

    snapshot = RuntimeStatusCollector(redis_url="").collect(bot, repo_path=tmp_path)

    assert snapshot.ok is True
    assert snapshot.sources == ["file:state.json"]
    assert "no_signal" in snapshot.text
    assert snapshot.payloads["file:state.json"]["open_positions"] == 0


def test_variable_plan_requires_allowlist_and_mapping(now_utc) -> None:
    bot = BotConfig(
        id="spot",
        name="Spot",
        github_repo="owner/repo",
        allow_parameter_overlays=True,
        allowed_overlay_types=["threshold_adjustment"],
        managed_railway_variables=["SCORE_THRESHOLD_ADJUSTMENT"],
        railway_variable_mappings={"threshold_adjustment:score_threshold": "SCORE_THRESHOLD_ADJUSTMENT"},
    )
    logs = LogAnalysis(1, 0, 0, 0, 0, 0, 0, 0, top_blockers=[("score_threshold", 3)])
    backtest = BacktestResult(True, ["python", "bt.py"], 0, "", total_trades=10, total_pnl=4.0)

    recommendations = build_recommendations(bot, logs, backtest)
    overlays = build_safe_overlays(bot, recommendations, generated_at=now_utc)
    plan = build_railway_variable_plan(bot, recommendations, overlays, generated_at=now_utc)

    assert len(plan["proposals"]) == 1
    assert plan["proposals"][0]["variable"] == "SCORE_THRESHOLD_ADJUSTMENT"
    assert plan["proposals"][0]["requires_manual_approval"] is True