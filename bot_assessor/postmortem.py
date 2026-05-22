from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from bot_assessor.backtest import BacktestResult
from bot_assessor.config import BotConfig
from bot_assessor.logs import LogAnalysis
from bot_assessor.portfolio import PortfolioSummary


@dataclass(frozen=True)
class PostMortemFinding:
    severity: str
    cause: str
    evidence: str
    action: str


@dataclass(frozen=True)
class PostMortemReport:
    headline: str
    severity: str
    findings: list[PostMortemFinding] = field(default_factory=list)
    improvement_hypotheses: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_postmortem(
    bot: BotConfig,
    *,
    logs: LogAnalysis,
    backtest: BacktestResult | None,
    portfolio: PortfolioSummary,
) -> PostMortemReport:
    findings: list[PostMortemFinding] = []
    hypotheses: list[dict[str, Any]] = []
    if logs.errors:
        findings.append(
            PostMortemFinding(
                "high",
                "Production runtime errors",
                f"{logs.errors} error or exception lines appeared in the review window.",
                "Repair production stability before increasing risk or changing strategy thresholds.",
            )
        )
    if logs.order_not_filled:
        findings.append(
            PostMortemFinding(
                "high",
                "Execution rejects or no-fills",
                f"{logs.order_not_filled} no-fill/reject events were detected.",
                "Check margin, precision, minimum trade size, spread, and broker-side order validation.",
            )
        )
        hypotheses.append(_hypothesis("execution_sizing_guard", "Tighten sizing and precision guards", "execution", "No-fill count must fall without reducing profitable trade count."))
    if logs.stale_data_hits:
        findings.append(
            PostMortemFinding(
                "medium",
                "Stale or missing data inputs",
                f"{logs.stale_data_hits} stale-data references were detected.",
                "Block new entries when data freshness is uncertain and repair provider refresh jobs.",
            )
        )
        hypotheses.append(_hypothesis("freshness_entry_block", "Block entries on stale data", "data_quality", "Backtests and live dry-runs should show fewer stale-data entries."))
    if backtest is None:
        findings.append(PostMortemFinding("medium", "Backtest unavailable", "No rolling backtest was run.", "Do not apply candidate changes until a comparable baseline exists."))
    elif not backtest.ok:
        findings.append(PostMortemFinding("high", "Backtest failed", backtest.error or "The configured backtest returned a non-zero status.", "Fix the backtest command before promoting strategy changes."))
    else:
        if backtest.total_trades == 0:
            findings.append(PostMortemFinding("medium", "No rolling-backtest sample", "The rolling replay produced zero trades.", "Do not optimize thresholds until enough setups exist; inspect whether gates are too restrictive."))
        if backtest.total_pnl is not None and backtest.total_pnl < 0:
            findings.append(PostMortemFinding("high", "Negative rolling expectancy", f"Rolling P&L was {backtest.total_pnl:.4f}.", "Generate a candidate that blocks the weakest lane/symbol/regime and prove it on 30d and longer windows."))
            hypotheses.append(_hypothesis("negative_expectancy_gate", "Block or tighten underperforming lanes", "strategy_gate", "Candidate P&L, PF, and drawdown must beat baseline on every configured window."))
        if backtest.profit_factor is not None and backtest.profit_factor < 1.0:
            findings.append(PostMortemFinding("high", "Profit factor below break-even", f"Profit factor was {backtest.profit_factor:.4f}.", "Prioritize reducing losing trades over adding throughput."))
        if backtest.max_drawdown is not None and abs(backtest.max_drawdown) > 0.12:
            findings.append(PostMortemFinding("medium", "Drawdown pressure", f"Max drawdown was {backtest.max_drawdown:.2%}.", "Lower risk, improve stop discipline, or add regime blocks before scaling exposure."))
            hypotheses.append(_hypothesis("drawdown_risk_cap", "Reduce risk in drawdown-prone regimes", "risk_control", "Candidate drawdown must not worsen and P&L should remain positive."))
    for blocker, count in logs.top_blockers[:3]:
        findings.append(
            PostMortemFinding(
                "medium",
                "Missed-opportunity blocker",
                f"{blocker} blocked {count} opportunity records.",
                "Run a targeted candidate backtest for this gate; lower it only when expectancy improves after costs.",
            )
        )
        hypotheses.append(_hypothesis(f"blocker_{_slug(blocker)}", f"Backtest targeted adjustment for {blocker}", "threshold", "Adjustment must improve P&L without worse PF or drawdown."))
    if portfolio.risk_at_stop_pct_nav is not None and portfolio.risk_at_stop_pct_nav > 5.0:
        findings.append(PostMortemFinding("high", "Open risk concentration", f"Open stop risk is {portfolio.risk_at_stop_pct_nav:.2f}% of NAV.", "Cap portfolio risk before allowing additional entries."))
        hypotheses.append(_hypothesis("portfolio_risk_cap", "Cap simultaneous open stop risk", "portfolio_risk", "Open risk should fall below cap without reducing 30d P&L quality."))
    if _broker_sync_ambiguity(logs):
        findings.append(PostMortemFinding("medium", "Broker-sync close ambiguity", "Logs mention broker positions no longer being open.", "Preserve broker close reason, realized P&L, margin, and stop-risk context in lifecycle messages."))
    if not findings:
        findings.append(PostMortemFinding("info", "No material post-mortem issue", "Logs, runtime status, and backtest did not surface an urgent failure.", "Keep collecting sample size and test only incremental improvements."))
    severity = _max_severity(findings)
    return PostMortemReport(headline=_headline(bot, severity, findings), severity=severity, findings=findings, improvement_hypotheses=_dedupe_hypotheses(hypotheses))


def _hypothesis(identifier: str, title: str, change_type: str, validation: str) -> dict[str, Any]:
    return {"id": identifier[:80], "title": title, "change_type": change_type, "validation": validation}


def _dedupe_hypotheses(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _broker_sync_ambiguity(logs: LogAnalysis) -> bool:
    markers = ("not_in_oanda_open_positions", "no longer open", "broker reported closed", "open-position sync")
    return any(any(marker in line.lower() for marker in markers) for line in logs.noteworthy_lines)


def _max_severity(findings: list[PostMortemFinding]) -> str:
    rank = {"info": 0, "low": 1, "medium": 2, "high": 3}
    return max((item.severity for item in findings), key=lambda value: rank.get(value, 0), default="info")


def _headline(bot: BotConfig, severity: str, findings: list[PostMortemFinding]) -> str:
    if severity == "high":
        return f"{bot.name} needs risk or reliability work before scaling."
    if severity == "medium":
        return f"{bot.name} has optimization candidates that need backtest proof."
    return f"{bot.name} has no urgent post-mortem issue."


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")[:48] or "unknown"