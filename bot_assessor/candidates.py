from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


POSTURES = {"defensive_tighten", "quality_tighten", "selective_expand"}


@dataclass(frozen=True)
class NumericPatch:
    path: str
    label: str
    pattern: str
    adjustments: dict[str, float]
    min_value: float
    max_value: float
    precision: int = 4
    mode: str = "add"


@dataclass(frozen=True)
class AppliedPatch:
    path: str
    label: str
    old_value: float
    new_value: float
    posture: str


@dataclass(frozen=True)
class CandidateGenerationResult:
    ok: bool
    bot_id: str
    generator: str
    posture: str
    changed_files: list[str]
    applied_patches: list[AppliedPatch] = field(default_factory=list)
    audit_file: str | None = None
    error: str | None = None

    @property
    def output(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)


GENERATOR_ALIASES = {
    "mexc_spot": "mexc_spot_thresholds",
    "mexc_futures": "mexc_futures_thresholds",
    "forex": "forex_risk_caps",
    "gold": "gold_risk_caps",
    "indices": "indices_score_thresholds",
    "commodities": "commodities_risk_caps",
    "bonds": "bonds_dv01_caps",
}


GENERATOR_BOT_IDS = {value: key for key, value in GENERATOR_ALIASES.items()}


PATCH_PROFILES: dict[str, list[NumericPatch]] = {
    "mexc_spot_thresholds": [
        NumericPatch(
            path="mexcbot/config.py",
            label="runtime_score_threshold",
            pattern=r'(?P<prefix>score_threshold=env_float\("SCORE_THRESHOLD",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 2.0, "quality_tighten": 1.0, "selective_expand": -1.0},
            min_value=30.0,
            max_value=60.0,
            precision=1,
        ),
        NumericPatch(
            path="mexcbot/config.py",
            label="runtime_scalper_threshold",
            pattern=r'(?P<prefix>scalper_threshold=env_float\("SCALPER_THRESHOLD", env_float\("SCORE_THRESHOLD",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\)\))',
            adjustments={"defensive_tighten": 2.0, "quality_tighten": 1.0, "selective_expand": -1.0},
            min_value=34.0,
            max_value=66.0,
            precision=1,
        ),
        NumericPatch(
            path="backtest/config.py",
            label="backtest_score_threshold",
            pattern=r'(?P<prefix>score_threshold=env_float\("BACKTEST_SCORE_THRESHOLD", env_float\("SCORE_THRESHOLD",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\)\))',
            adjustments={"defensive_tighten": 2.0, "quality_tighten": 1.0, "selective_expand": -1.0},
            min_value=30.0,
            max_value=60.0,
            precision=1,
        ),
        NumericPatch(
            path="backtest/config.py",
            label="backtest_scalper_threshold",
            pattern=r'(?P<prefix>scalper_threshold=env_float\("BACKTEST_SCALPER_THRESHOLD", env_float\("SCALPER_THRESHOLD", env_float\("SCORE_THRESHOLD",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\)\)\))',
            adjustments={"defensive_tighten": 2.0, "quality_tighten": 1.0, "selective_expand": -1.0},
            min_value=34.0,
            max_value=66.0,
            precision=1,
        ),
    ],
    "mexc_futures_thresholds": [
        NumericPatch(
            path="futuresbot/config.py",
            label="runtime_score_threshold",
            pattern=r'(?P<prefix>min_confidence_score=env_float\("FUTURES_SCORE_THRESHOLD", opportunity_min_raw_score\(\) if opportunity_bucket_sizing_enabled\(\) else\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 2.0, "quality_tighten": 1.0, "selective_expand": -1.0},
            min_value=45.0,
            max_value=80.0,
            precision=1,
        ),
        NumericPatch(
            path="futuresbot/config.py",
            label="hard_loss_cap_pct",
            pattern=r'(?P<prefix>hard_loss_cap_pct=env_float\("FUTURES_HARD_LOSS_CAP_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": -0.10, "quality_tighten": -0.05, "selective_expand": 0.0},
            min_value=0.25,
            max_value=0.75,
            precision=3,
        ),
    ],
    "indices_score_thresholds": [
        NumericPatch(
            path="indicesbot/config.py",
            label="runtime_min_score",
            pattern=r'(?P<prefix>min_score=env_float\("INDICES_MIN_SCORE",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 2.0, "quality_tighten": 1.0, "selective_expand": -1.0},
            min_value=68.0,
            max_value=90.0,
            precision=1,
        ),
        NumericPatch(
            path="indicesbot/backtest/run_backtest.py",
            label="backtest_min_score",
            pattern=r'(?P<prefix>parser\.add_argument\("--min-score", type=float, default=)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 2.0, "quality_tighten": 1.0, "selective_expand": -1.0},
            min_value=64.0,
            max_value=88.0,
            precision=1,
        ),
    ],
    "gold_risk_caps": [
        NumericPatch(
            path="goldbot/config.py",
            label="max_risk_per_trade",
            pattern=r'(?P<prefix>max_risk_per_trade=env_float\("MAX_RISK_PER_TRADE",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.85, "quality_tighten": 0.95, "selective_expand": 1.05},
            min_value=0.003,
            max_value=0.012,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="goldbot/config.py",
            label="max_total_gold_risk",
            pattern=r'(?P<prefix>max_total_gold_risk=env_float\("MAX_TOTAL_GOLD_RISK",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.90, "quality_tighten": 0.95, "selective_expand": 1.05},
            min_value=0.012,
            max_value=0.05,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="goldbot/config.py",
            label="event_adverse_risk_multiplier",
            pattern=r'(?P<prefix>gold_event_adverse_risk_multiplier=env_float\("GOLD_EVENT_ADVERSE_RISK_MULTIPLIER",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": -0.08, "quality_tighten": -0.03, "selective_expand": 0.03},
            min_value=0.25,
            max_value=0.70,
            precision=3,
        ),
    ],
    "forex_risk_caps": [
        NumericPatch(
            path="main.py",
            label="runtime_max_risk_per_trade",
            pattern=r'(?P<prefix>MAX_RISK_PER_TRADE\s*=\s*float\(os\.getenv\("MAX_RISK_PER_TRADE",\s*")(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>"\)\))',
            adjustments={"defensive_tighten": 0.85, "quality_tighten": 0.95, "selective_expand": 1.05},
            min_value=0.006,
            max_value=0.02,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="backtest/config.py",
            label="backtest_max_risk_per_trade",
            pattern=r'(?P<prefix>max_risk_per_trade=env_float\("BACKTEST_MAX_RISK_PER_TRADE", env_float\("MAX_RISK_PER_TRADE",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\)\))',
            adjustments={"defensive_tighten": 0.85, "quality_tighten": 0.95, "selective_expand": 1.05},
            min_value=0.006,
            max_value=0.02,
            precision=5,
            mode="multiply",
        ),
    ],
    "commodities_risk_caps": [
        NumericPatch(
            path="commoditiesbot/config.py",
            label="max_total_risk_pct",
            pattern=r'(?P<prefix>max_total_risk_pct=_float\("MAX_TOTAL_RISK_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.90, "quality_tighten": 0.96, "selective_expand": 1.05},
            min_value=0.015,
            max_value=0.04,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="commoditiesbot/config.py",
            label="energy_bucket_risk_pct",
            pattern=r'(?P<prefix>energy_bucket_risk_pct=_float\("ENERGY_BUCKET_RISK_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.90, "quality_tighten": 0.96, "selective_expand": 1.05},
            min_value=0.006,
            max_value=0.016,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="commoditiesbot/config.py",
            label="grains_bucket_risk_pct",
            pattern=r'(?P<prefix>grains_bucket_risk_pct=_float\("GRAINS_BUCKET_RISK_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.90, "quality_tighten": 0.96, "selective_expand": 1.05},
            min_value=0.005,
            max_value=0.014,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="commoditiesbot/config.py",
            label="softs_bucket_risk_pct",
            pattern=r'(?P<prefix>softs_bucket_risk_pct=_float\("SOFTS_BUCKET_RISK_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.90, "quality_tighten": 0.96, "selective_expand": 1.05},
            min_value=0.004,
            max_value=0.011,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="commoditiesbot/config.py",
            label="profit_lock_trigger_pct",
            pattern=r'(?P<prefix>profit_lock_trigger_pct=_float\("PROFIT_LOCK_TRIGGER_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": -0.40, "quality_tighten": -0.20, "selective_expand": 0.20},
            min_value=1.5,
            max_value=5.0,
            precision=2,
        ),
        NumericPatch(
            path="commoditiesbot/config.py",
            label="profit_lock_pullback_pct",
            pattern=r'(?P<prefix>profit_lock_pullback_pct=_float\("PROFIT_LOCK_PULLBACK_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": -0.20, "quality_tighten": -0.10, "selective_expand": 0.10},
            min_value=0.75,
            max_value=3.0,
            precision=2,
        ),
    ],
    "bonds_dv01_caps": [
        NumericPatch(
            path="bondsbot/config.py",
            label="portfolio_dv01_cap",
            pattern=r'(?P<prefix>max_portfolio_dv01_nav_10bp=_float\("MAX_PORTFOLIO_DV01_NAV_10BP",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.90, "quality_tighten": 0.96, "selective_expand": 1.05},
            min_value=0.0025,
            max_value=0.007,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="bondsbot/config.py",
            label="country_dv01_cap",
            pattern=r'(?P<prefix>max_country_dv01_nav_10bp=_float\("MAX_COUNTRY_DV01_NAV_10BP",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.90, "quality_tighten": 0.96, "selective_expand": 1.05},
            min_value=0.0015,
            max_value=0.0045,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="bondsbot/config.py",
            label="tenor_dv01_cap",
            pattern=r'(?P<prefix>max_tenor_dv01_nav_10bp=_float\("MAX_TENOR_DV01_NAV_10BP",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 0.90, "quality_tighten": 0.96, "selective_expand": 1.05},
            min_value=0.001,
            max_value=0.003,
            precision=5,
            mode="multiply",
        ),
        NumericPatch(
            path="bondsbot/config.py",
            label="min_live_unit_score",
            pattern=r'(?P<prefix>min_live_unit_score=_float\("BONDS_MIN_LIVE_UNIT_SCORE",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": 2.0, "quality_tighten": 1.0, "selective_expand": -1.0},
            min_value=72.0,
            max_value=88.0,
            precision=1,
        ),
        NumericPatch(
            path="bondsbot/config.py",
            label="profit_lock_trigger_pct",
            pattern=r'(?P<prefix>profit_lock_trigger_pct=_float\("PROFIT_LOCK_TRIGGER_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": -2.0, "quality_tighten": -1.0, "selective_expand": 1.0},
            min_value=8.0,
            max_value=20.0,
            precision=1,
        ),
        NumericPatch(
            path="bondsbot/config.py",
            label="profit_lock_pullback_pct",
            pattern=r'(?P<prefix>profit_lock_pullback_pct=_float\("PROFIT_LOCK_PULLBACK_PCT",\s*)(?P<value>[-+]?\d+(?:\.\d+)?)(?P<suffix>\))',
            adjustments={"defensive_tighten": -0.30, "quality_tighten": -0.15, "selective_expand": 0.15},
            min_value=1.0,
            max_value=3.0,
            precision=2,
        ),
    ],
}


def generate_candidate(
    generator: str,
    *,
    repo_path: str | Path = ".",
    bot_id: str | None = None,
    context: Mapping[str, Any] | None = None,
    posture: str | None = None,
    generated_at: datetime | None = None,
) -> CandidateGenerationResult:
    resolved_generator = GENERATOR_ALIASES.get(generator, generator)
    resolved_bot_id = bot_id or GENERATOR_BOT_IDS.get(resolved_generator) or generator
    patches = PATCH_PROFILES.get(resolved_generator)
    if not patches:
        return CandidateGenerationResult(False, resolved_bot_id, resolved_generator, posture or "unknown", [], error=f"unknown candidate generator: {generator}")
    repo = Path(repo_path).resolve()
    selected_posture = posture or choose_posture(context or {})
    if selected_posture not in POSTURES:
        return CandidateGenerationResult(False, resolved_bot_id, resolved_generator, selected_posture, [], error=f"unsupported candidate posture: {selected_posture}")

    applied: list[AppliedPatch] = []
    changed_files: set[str] = set()
    try:
        for patch in patches:
            applied_patch = _apply_numeric_patch(repo, patch, selected_posture)
            if applied_patch is not None:
                applied.append(applied_patch)
                changed_files.add(patch.path)
        audit_file = _write_audit_file(
            repo,
            bot_id=resolved_bot_id,
            generator=resolved_generator,
            posture=selected_posture,
            context=context or {},
            applied=applied,
            generated_at=generated_at or datetime.now(timezone.utc),
        )
        changed_files.add(audit_file)
    except Exception as exc:
        return CandidateGenerationResult(False, resolved_bot_id, resolved_generator, selected_posture, sorted(changed_files), applied, error=str(exc))

    return CandidateGenerationResult(
        ok=True,
        bot_id=resolved_bot_id,
        generator=resolved_generator,
        posture=selected_posture,
        changed_files=sorted(changed_files),
        applied_patches=applied,
        audit_file="bot_assessor_candidate_config.json",
    )


def choose_posture(context: Mapping[str, Any]) -> str:
    metrics = _scenario_metrics(context)
    if not metrics:
        return "quality_tighten"
    if any(_is_defensive_candidate(item) for item in metrics):
        return "defensive_tighten"
    if all(_is_expansion_candidate(item) for item in metrics):
        return "selective_expand"
    return "quality_tighten"


def load_context(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_numeric_patch(repo: Path, patch: NumericPatch, posture: str) -> AppliedPatch | None:
    path = repo / patch.path
    if not path.exists():
        raise FileNotFoundError(f"candidate patch target missing: {patch.path}")
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(patch.pattern)
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"candidate patch pattern not found: {patch.path}:{patch.label}")
    current_value = float(match.group("value"))
    adjustment = float(patch.adjustments[posture])
    proposed = current_value * adjustment if patch.mode == "multiply" else current_value + adjustment
    new_value = min(patch.max_value, max(patch.min_value, proposed))
    new_value = round(new_value, patch.precision)
    if new_value == round(current_value, patch.precision):
        return None
    rendered = _format_value(new_value, patch.precision)
    replacement = f"{match.group('prefix')}{rendered}{match.group('suffix')}"
    updated = text[: match.start()] + replacement + text[match.end() :]
    path.write_text(updated, encoding="utf-8")
    return AppliedPatch(path=patch.path, label=patch.label, old_value=current_value, new_value=new_value, posture=posture)


def _write_audit_file(
    repo: Path,
    *,
    bot_id: str,
    generator: str,
    posture: str,
    context: Mapping[str, Any],
    applied: list[AppliedPatch],
    generated_at: datetime,
) -> str:
    relative = "bot_assessor_candidate_config.json"
    payload = {
        "schema_version": "1.0",
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "bot_id": bot_id,
        "generator": generator,
        "posture": posture,
        "baseline_backtests": dict(context.get("baseline_backtests", {})) if isinstance(context.get("baseline_backtests"), Mapping) else {},
        "applied_patches": [asdict(item) for item in applied],
        "promotion_rule": "PR may be opened only when tests pass and candidate backtests beat all configured baselines.",
    }
    (repo / relative).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return relative


def _scenario_metrics(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = context.get("baseline_backtests", {})
    if not isinstance(raw, Mapping):
        return []
    rows = []
    for value in raw.values():
        if isinstance(value, Mapping):
            rows.append(dict(value))
    return rows


def _is_defensive_candidate(metrics: Mapping[str, Any]) -> bool:
    pnl = _float(metrics.get("total_pnl"))
    ret = _float(metrics.get("return_pct"))
    profit_factor = _float(metrics.get("profit_factor"))
    drawdown = abs(_float(metrics.get("max_drawdown")) or 0.0)
    return (pnl is not None and pnl < 0.0) or (ret is not None and ret < 0.0) or (profit_factor is not None and profit_factor < 1.0) or drawdown >= 0.08


def _is_expansion_candidate(metrics: Mapping[str, Any]) -> bool:
    trades = _float(metrics.get("total_trades")) or 0.0
    pnl = _float(metrics.get("total_pnl"))
    ret = _float(metrics.get("return_pct"))
    profit_factor = _float(metrics.get("profit_factor"))
    drawdown = abs(_float(metrics.get("max_drawdown")) or 0.0)
    return trades >= 3 and (pnl is not None and pnl > 0.0) and (ret is not None and ret >= 0.02) and (profit_factor is not None and profit_factor >= 1.35) and drawdown <= 0.04


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_value(value: float, precision: int) -> str:
    if precision <= 0:
        return str(int(round(value)))
    if precision == 1:
        return f"{value:.1f}"
    text = f"{value:.{precision}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _context_from_env() -> dict[str, Any]:
    path = os.getenv("BOT_ASSESSOR_CANDIDATE_CONTEXT", "")
    if path:
        return load_context(path)
    raw = os.getenv("BOT_ASSESSOR_CANDIDATE_CONTEXT_JSON", "")
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bot_assessor.candidates")
    parser.add_argument("--bot", default=os.getenv("BOT_ASSESSOR_BOT_ID", ""))
    parser.add_argument("--generator", default="")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--context", default=os.getenv("BOT_ASSESSOR_CANDIDATE_CONTEXT", ""))
    parser.add_argument("--posture", choices=sorted(POSTURES), default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    generator = args.generator or args.bot
    context = load_context(args.context) if args.context else _context_from_env()
    result = generate_candidate(generator, repo_path=args.repo, bot_id=args.bot or None, context=context, posture=args.posture)
    print(result.output)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())