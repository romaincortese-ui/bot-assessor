from pathlib import Path

from bot_assessor.candidates import choose_posture, generate_candidate


def test_generate_mexc_spot_threshold_candidate(tmp_path: Path) -> None:
    (tmp_path / "mexcbot").mkdir()
    (tmp_path / "backtest").mkdir()
    (tmp_path / "mexcbot" / "config.py").write_text(
        'score_threshold=env_float("SCORE_THRESHOLD", 37.0)\n'
        'scalper_threshold=env_float("SCALPER_THRESHOLD", env_float("SCORE_THRESHOLD", 42.0))\n',
        encoding="utf-8",
    )
    (tmp_path / "backtest" / "config.py").write_text(
        'score_threshold=env_float("BACKTEST_SCORE_THRESHOLD", env_float("SCORE_THRESHOLD", 37.0))\n'
        'scalper_threshold=env_float("BACKTEST_SCALPER_THRESHOLD", env_float("SCALPER_THRESHOLD", env_float("SCORE_THRESHOLD", 42.0)))\n',
        encoding="utf-8",
    )

    result = generate_candidate(
        "mexc_spot",
        repo_path=tmp_path,
        context={"baseline_backtests": {"30d": {"total_pnl": -4.0, "profit_factor": 0.8, "max_drawdown": -0.03}}},
    )

    assert result.ok
    assert result.posture == "defensive_tighten"
    assert {patch.label for patch in result.applied_patches} == {
        "runtime_score_threshold",
        "runtime_scalper_threshold",
        "backtest_score_threshold",
        "backtest_scalper_threshold",
    }
    assert "39.0" in (tmp_path / "mexcbot" / "config.py").read_text(encoding="utf-8")
    assert "44.0" in (tmp_path / "backtest" / "config.py").read_text(encoding="utf-8")
    assert (tmp_path / "bot_assessor_candidate_config.json").exists()


def test_generate_forex_risk_candidate_expands_only_when_baseline_is_strong(tmp_path: Path) -> None:
    (tmp_path / "backtest").mkdir()
    (tmp_path / "main.py").write_text(
        'MAX_RISK_PER_TRADE     = float(os.getenv("MAX_RISK_PER_TRADE",     "0.015"))\n',
        encoding="utf-8",
    )
    (tmp_path / "backtest" / "config.py").write_text(
        'max_risk_per_trade=env_float("BACKTEST_MAX_RISK_PER_TRADE", env_float("MAX_RISK_PER_TRADE", 0.015))\n',
        encoding="utf-8",
    )

    result = generate_candidate(
        "forex_risk_caps",
        repo_path=tmp_path,
        context={"baseline_backtests": {"90d": {"total_trades": 9, "total_pnl": 120.0, "return_pct": 0.04, "profit_factor": 1.6, "max_drawdown": -0.02}}},
    )

    assert result.ok
    assert result.posture == "selective_expand"
    assert "0.01575" in (tmp_path / "main.py").read_text(encoding="utf-8")
    assert "0.01575" in (tmp_path / "backtest" / "config.py").read_text(encoding="utf-8")


def test_choose_posture_defaults_to_quality_tighten_for_mixed_baseline() -> None:
    assert choose_posture({"baseline_backtests": {"30d": {"total_pnl": 10.0, "profit_factor": 1.1, "return_pct": 0.01, "max_drawdown": -0.03}}}) == "quality_tighten"


def test_unknown_generator_fails_cleanly(tmp_path: Path) -> None:
    result = generate_candidate("unknown", repo_path=tmp_path)

    assert not result.ok
    assert "unknown candidate generator" in (result.error or "")