from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot_assessor.portfolio import fleet_rollup


def render_markdown(reviews: list[dict[str, Any]], *, generated_at: datetime, window_hours: int) -> str:
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Daily Bot Assessment - {stamp}",
        "",
        f"Window: last {window_hours} hours",
        "",
        "## Fleet Summary",
        "",
        "| Bot | Health | Deploy | Commit | Live P&L | Risk@Stop | Trades | Backtest PnL | PF | Key issues |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for review in reviews:
        bt = review.get("backtest", {})
        logs = review.get("logs", {})
        portfolio = review.get("portfolio", {})
        issues = []
        if logs.get("errors"):
            issues.append(f"errors={logs['errors']}")
        if logs.get("order_not_filled"):
            issues.append(f"no_fill={logs['order_not_filled']}")
        if logs.get("stale_data_hits"):
            issues.append(f"stale={logs['stale_data_hits']}")
        if not issues:
            issues.append("none")
        lines.append(
            "| {bot} | {score} {state} | {deploy} | `{commit}` | {live_pnl} | {risk} | {trades} | {pnl} | {pf} | {issues} |".format(
                bot=review.get("bot_name"),
                score=review.get("health", {}).get("score"),
                state=review.get("health", {}).get("state"),
                deploy=_deployment_label(review),
                commit=review.get("production", {}).get("active_short_commit") or review.get("production", {}).get("short_commit"),
                live_pnl=_fmt_money(portfolio.get("live_pnl_amount"), portfolio.get("currency")),
                risk=_fmt_money(portfolio.get("risk_at_stop"), portfolio.get("currency")),
                trades=_fmt(bt.get("total_trades")),
                pnl=_fmt(bt.get("total_pnl")),
                pf=_fmt(bt.get("profit_factor")),
                issues=", ".join(issues),
            )
        )
    lines.extend(_render_rollup(fleet_rollup(reviews)))
    for review in reviews:
        lines.extend(_render_bot_section(review))
    return "\n".join(lines).strip() + "\n"


def write_artifacts(artifact_dir: str | Path, reviews: list[dict[str, Any]], markdown: str, *, generated_at: datetime) -> dict[str, str]:
    root = Path(artifact_dir)
    day_dir = root / generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    report_md = day_dir / "daily_report.md"
    report_json = day_dir / "daily_report.json"
    report_md.write_text(markdown, encoding="utf-8")
    report_json.write_text(json.dumps({"generated_at": generated_at.isoformat(), "reviews": reviews}, indent=2), encoding="utf-8")
    for review in reviews:
        (day_dir / f"{review['bot_id']}_review.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
    return {"markdown": str(report_md), "json": str(report_json), "directory": str(day_dir)}


def _render_bot_section(review: dict[str, Any]) -> list[str]:
    logs = review.get("logs", {})
    bt = review.get("backtest", {})
    production = review.get("production", {})
    railway = production.get("railway") or {}
    portfolio = review.get("portfolio", {})
    postmortem = review.get("postmortem", {})
    lines = [
        "",
        f"## {review.get('bot_name')}",
        "",
        f"Production: `{production.get('active_short_commit') or production.get('short_commit')}` - {production.get('commit_message')}",
        f"Railway: {railway.get('service') or production.get('railway_service')} / {railway.get('environment') or production.get('railway_environment')} - {_deployment_label(review)}",
        f"Health: {review.get('health', {}).get('score')} ({review.get('health', {}).get('state')})",
        f"Backtest: trades={_fmt(bt.get('total_trades'))}, pnl={_fmt(bt.get('total_pnl'))}, pf={_fmt(bt.get('profit_factor'))}, max_dd={_fmt_pct(bt.get('max_drawdown'))}",
        "Portfolio: "
        f"state={portfolio.get('state', 'n/a')}, decision={portfolio.get('decision', 'n/a')}, "
        f"live_pnl={_fmt_money(portfolio.get('live_pnl_amount'), portfolio.get('currency'))}, "
        f"risk_at_stop={_fmt_money(portfolio.get('risk_at_stop'), portfolio.get('currency'))} ({_fmt_pct_from_percent(portfolio.get('risk_at_stop_pct_nav'))} NAV), "
        f"margin={_fmt_money(portfolio.get('margin_used'), portfolio.get('currency'))} ({_fmt_pct_from_percent(portfolio.get('margin_used_pct_nav'))} NAV)",
        f"Logs: errors={logs.get('errors')}, warnings={logs.get('warnings')}, no_fills={logs.get('order_not_filled')}, missed={logs.get('missed_opportunity_count')}",
        "",
        "Post-mortem:",
        f"- {postmortem.get('headline', 'No post-mortem available')}",
    ]
    for finding in (postmortem.get("findings") or [])[:5]:
        lines.append(f"- **{str(finding.get('severity', 'info')).upper()}** {finding.get('cause')}: {finding.get('action')}")
    hypotheses = postmortem.get("improvement_hypotheses") or []
    if hypotheses:
        lines.append("Improvement hypotheses:")
        for item in hypotheses[:5]:
            lines.append(f"- {item.get('title')} ({item.get('change_type')}): {item.get('validation')}")
    lines.extend([
        "",
        "Recommendations:",
    ])
    for item in review.get("recommendations", []):
        lines.append(f"- **{item.get('severity', 'info').upper()}** {item.get('title')}: {item.get('action')}")
    overlays = review.get("parameter_overlays", [])
    if overlays:
        lines.append("")
        lines.append(f"Parameter overlays prepared: {len(overlays)}")
    variable_plan = review.get("railway_variable_plan") or {}
    proposals = variable_plan.get("proposals") or []
    blocked = variable_plan.get("blocked") or []
    if proposals or blocked:
        lines.append("")
        lines.append(f"Railway variable proposals: {len(proposals)} prepared, {len(blocked)} blocked by safety checks")
    noteworthy = logs.get("noteworthy_lines") or []
    if noteworthy:
        lines.append("")
        lines.append("Noteworthy log lines:")
        for line in noteworthy[:5]:
            lines.append(f"- `{line[:180]}`")
    return lines


def _render_rollup(rollup: dict[str, Any]) -> list[str]:
    lines = ["", "## Portfolio Rollup", ""]
    by_currency = rollup.get("by_currency") or {}
    if not by_currency:
        lines.append("No normalized live portfolio metrics were available.")
    for currency, values in by_currency.items():
        lines.append(
            f"- {currency}: live P&L {_fmt_money(values.get('live_pnl_amount'), currency)}, "
            f"risk@stop {_fmt_money(values.get('risk_at_stop'), currency)}, margin {_fmt_money(values.get('margin_used'), currency)}"
        )
    best = rollup.get("best_backtest")
    worst = rollup.get("worst_backtest")
    if best:
        lines.append(f"- Best rolling backtest: {best.get('bot')} ({_fmt(best.get('pnl'))})")
    if worst:
        lines.append(f"- Weakest rolling backtest: {worst.get('bot')} ({_fmt(worst.get('pnl'))})")
    attention = rollup.get("attention") or []
    if attention:
        lines.append(f"- Needs attention: {', '.join(attention)}")
    return lines


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct_from_percent(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_money(value: Any, currency: Any) -> str:
    if value is None:
        return "n/a"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    code = str(currency or "").upper()
    symbol = "$" if code == "USD" else "£" if code == "GBP" else f"{code} " if code else ""
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{symbol}{abs(amount):.2f}"


def _deployment_label(review: dict[str, Any]) -> str:
    railway = (review.get("production") or {}).get("railway") or {}
    status = railway.get("status") or "unknown"
    if railway.get("ok") is False:
        return f"unknown ({railway.get('error') or 'status unavailable'})"
    return str(status)