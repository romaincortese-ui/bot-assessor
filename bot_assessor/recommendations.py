from __future__ import annotations

from bot_assessor.backtest import BacktestResult
from bot_assessor.config import BotConfig
from bot_assessor.logs import LogAnalysis
from bot_assessor.review import Recommendation


def build_recommendations(bot: BotConfig, logs: LogAnalysis, backtest: BacktestResult | None) -> list[Recommendation]:
    recommendations: list[Recommendation] = []
    if logs.errors:
        recommendations.append(
            Recommendation(
                severity="high",
                title="Investigate production errors",
                rationale=f"The last window contains {logs.errors} error/exception lines.",
                action="Review noteworthy log lines before changing strategy parameters.",
            )
        )
    if logs.order_not_filled:
        recommendations.append(
            Recommendation(
                severity="high",
                title="Review broker/exchange execution rejects",
                rationale=f"Detected {logs.order_not_filled} no-fill or rejected-order log lines.",
                action="Check sizing, margin, instrument precision, and order-fill validation before allowing new risk.",
            )
        )
    if logs.stale_data_hits:
        recommendations.append(
            Recommendation(
                severity="medium",
                title="Refresh stale data inputs",
                rationale=f"Detected {logs.stale_data_hits} stale or missing-data references.",
                action="Check macro/event/data cron freshness and provider failures.",
            )
        )
    if logs.top_blockers:
        blocker, count = logs.top_blockers[0]
        overlay = None
        if bot.allow_parameter_overlays and "threshold" in blocker.lower():
            overlay = {"type": "threshold_adjustment", "target": blocker, "direction": "review", "max_step": 0.05}
        recommendations.append(
            Recommendation(
                severity="medium",
                title="Review top missed-opportunity blocker",
                rationale=f"Top blocker was {blocker!r} across {count} missed-opportunity records.",
                action="Compare this gate against the backtest before relaxing it.",
                overlay=overlay,
            )
        )
    if backtest is None:
        recommendations.append(
            Recommendation("medium", "Backtest was skipped", "No backtest result is available for this run.", "Run the configured 30-day command before applying overlays."),
        )
    elif not backtest.ok:
        recommendations.append(
            Recommendation("high", "Backtest command failed", "The configured backtest did not complete successfully.", "Fix the backtest/runtime environment before tuning the bot."),
        )
    else:
        if backtest.total_trades == 0:
            recommendations.append(
                Recommendation("medium", "No trades in rolling backtest", "The 30-day replay produced no trades.", "Assess whether the bot is too selective or whether market conditions genuinely lacked setups."),
            )
        if backtest.total_pnl is not None and backtest.total_pnl < 0:
            overlay = None
            if bot.allow_parameter_overlays:
                overlay = {"type": "score_offset", "target": "global", "value": 2.0, "ttl_hours": 72}
            recommendations.append(
                Recommendation("high", "Rolling backtest is negative", f"Backtest PnL was {backtest.total_pnl:.4f}.", "Tighten entries or block underperforming lanes until a weekly replay confirms recovery.", overlay=overlay),
            )
        if backtest.max_drawdown is not None and backtest.max_drawdown < -0.15:
            recommendations.append(
                Recommendation("medium", "Drawdown is elevated", f"Max drawdown was {backtest.max_drawdown:.2%}.", "Review stop-loss and risk caps before increasing opportunity throughput."),
            )
    if not recommendations:
        recommendations.append(Recommendation("info", "No urgent action", "Logs and backtest did not surface a critical issue.", "Keep collecting daily reviews and wait for enough sample size before tuning."))
    return recommendations