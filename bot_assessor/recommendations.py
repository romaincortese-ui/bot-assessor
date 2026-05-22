from __future__ import annotations

from bot_assessor.backtest import BacktestResult
from bot_assessor.config import BotConfig
from bot_assessor.logs import LogAnalysis
from bot_assessor.portfolio import PortfolioSummary
from bot_assessor.postmortem import PostMortemReport
from bot_assessor.review import Recommendation


def build_recommendations(
    bot: BotConfig,
    logs: LogAnalysis,
    backtest: BacktestResult | None,
    *,
    portfolio: PortfolioSummary | None = None,
    postmortem: PostMortemReport | None = None,
) -> list[Recommendation]:
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
        if bot.allow_parameter_overlays and ("threshold" in blocker.lower() or "score" in blocker.lower()):
            overlay = {"type": "threshold_adjustment", "target": blocker, "direction": _threshold_direction(backtest), "max_step": 0.05}
        recommendations.append(
            Recommendation(
                severity="medium",
                title="Review top missed-opportunity blocker",
                rationale=f"Top blocker was {blocker!r} across {count} missed-opportunity records.",
                action=f"Backtest a {overlay['direction'] if overlay else 'targeted'} adjustment for this gate before changing live risk.",
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
    if portfolio is not None:
        if portfolio.risk_at_stop_pct_nav is not None and portfolio.risk_at_stop_pct_nav > 5.0:
            recommendations.append(
                Recommendation(
                    "high",
                    "Open risk is above portfolio comfort zone",
                    f"Risk at stop is {portfolio.risk_at_stop_pct_nav:.2f}% of NAV.",
                    "Cap new entries and backtest a lower simultaneous-risk ceiling before scaling this bot.",
                )
            )
        if portfolio.margin_used_pct_nav is not None and portfolio.margin_used_pct_nav > 30.0:
            recommendations.append(
                Recommendation(
                    "medium",
                    "Margin usage is elevated",
                    f"Margin/collateral usage is {portfolio.margin_used_pct_nav:.2f}% of NAV.",
                    "Avoid adding correlated exposure until open risk and margin normalize.",
                )
            )
    if postmortem is not None and postmortem.improvement_hypotheses:
        recommendations.append(
            Recommendation(
                "medium" if postmortem.severity != "high" else "high",
                "Backtest post-mortem hypotheses",
                f"Post-mortem generated {len(postmortem.improvement_hypotheses)} candidate hypotheses.",
                "Run the weekly optimizer with deterministic candidates and promote only if all baseline gates improve.",
            )
        )
    if not recommendations:
        recommendations.append(Recommendation("info", "No urgent action", "Logs and backtest did not surface a critical issue.", "Keep collecting daily reviews and wait for enough sample size before tuning."))
    return recommendations


def _threshold_direction(backtest: BacktestResult | None) -> str:
    if backtest is not None and backtest.ok and backtest.total_pnl is not None and backtest.total_pnl < 0:
        return "raise"
    return "lower"