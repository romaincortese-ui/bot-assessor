from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from bot_assessor.backtest import BacktestResult
from bot_assessor.config import BotConfig
from bot_assessor.logs import LogAnalysis
from bot_assessor.repository import GitInfo


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class Recommendation:
    severity: str
    title: str
    rationale: str
    action: str
    overlay: dict[str, Any] | None = None


@dataclass(frozen=True)
class BotReview:
    schema_version: str
    bot_id: str
    bot_name: str
    generated_at: str
    window_hours: int
    maturity: str
    production: dict[str, Any]
    health: dict[str, Any]
    logs: dict[str, Any]
    runtime_status: dict[str, Any]
    backtest: dict[str, Any]
    recommendations: list[dict[str, Any]]
    parameter_overlays: list[dict[str, Any]] = field(default_factory=list)
    railway_variable_plan: dict[str, Any] = field(default_factory=dict)


def build_review(
    bot: BotConfig,
    *,
    generated_at: datetime,
    window_hours: int,
    git_info: GitInfo,
    logs: LogAnalysis,
    backtest: BacktestResult | None,
    recommendations: list[Recommendation],
    overlays: list[dict[str, Any]],
    deployment_status: dict[str, Any] | None = None,
    runtime_status: dict[str, Any] | None = None,
    railway_variable_plan: dict[str, Any] | None = None,
) -> BotReview:
    health_score = _health_score(logs, backtest, deployment_status)
    local_git = {
        "repo": bot.github_repo,
        "branch": git_info.branch,
        "commit": git_info.commit,
        "short_commit": git_info.short_commit,
        "commit_message": git_info.message,
        "dirty": git_info.dirty,
    }
    railway = deployment_status or {
        "ok": False,
        "service": bot.railway_service,
        "environment": bot.railway_environment,
        "error": "Railway deployment status was not collected",
    }
    return BotReview(
        schema_version=SCHEMA_VERSION,
        bot_id=bot.id,
        bot_name=bot.name,
        generated_at=generated_at.astimezone(timezone.utc).isoformat(),
        window_hours=window_hours,
        maturity=bot.maturity,
        production={
            **local_git,
            "local_git": local_git,
            "railway": railway,
            "active_commit": railway.get("commit") or git_info.commit,
            "active_short_commit": railway.get("short_commit") or git_info.short_commit,
            "deployment_status": railway.get("status"),
            "railway_service": bot.railway_service,
            "railway_environment": bot.railway_environment,
        },
        health={
            "score": health_score,
            "state": "healthy" if health_score >= 80 else "watch" if health_score >= 55 else "attention",
        },
        logs={
            "total_lines": logs.total_lines,
            "errors": logs.errors,
            "warnings": logs.warnings,
            "order_opened": logs.order_opened,
            "order_closed": logs.order_closed,
            "order_not_filled": logs.order_not_filled,
            "skip_events": logs.skip_events,
            "stale_data_hits": logs.stale_data_hits,
            "missed_opportunity_count": len(logs.missed_opportunities),
            "top_blockers": [{"reason": key, "count": count} for key, count in logs.top_blockers],
            "noteworthy_lines": logs.noteworthy_lines,
        },
        runtime_status=runtime_status or {"ok": False, "sources": [], "payloads": {}, "errors": ["Runtime status was not collected"]},
        backtest=_backtest_payload(backtest),
        recommendations=[asdict(item) for item in recommendations],
        parameter_overlays=overlays,
        railway_variable_plan=railway_variable_plan or {},
    )


def review_to_dict(review: BotReview) -> dict[str, Any]:
    return asdict(review)


def _backtest_payload(backtest: BacktestResult | None) -> dict[str, Any]:
    if backtest is None:
        return {"ok": False, "error": "Backtest skipped"}
    return {
        "ok": backtest.ok,
        "command": backtest.command,
        "returncode": backtest.returncode,
        "total_trades": backtest.total_trades,
        "total_pnl": backtest.total_pnl,
        "return_pct": backtest.return_pct,
        "profit_factor": backtest.profit_factor,
        "win_rate": backtest.win_rate,
        "max_drawdown": backtest.max_drawdown,
        "summary": backtest.summary or {},
        "error": backtest.error,
    }


def _health_score(logs: LogAnalysis, backtest: BacktestResult | None, deployment_status: dict[str, Any] | None = None) -> int:
    score = 100
    score -= min(35, logs.errors * 8)
    score -= min(15, logs.order_not_filled * 5)
    score -= min(15, logs.stale_data_hits * 3)
    if deployment_status:
        status = str(deployment_status.get("status") or "").lower()
        if status in {"failed", "crashed", "removed", "stopped", "error"}:
            score -= 35
        elif deployment_status.get("ok") is False:
            score -= 5
    if backtest is None or not backtest.ok:
        score -= 20
    elif backtest.total_pnl is not None and backtest.total_pnl < 0:
        score -= 15
    return max(0, min(100, score))