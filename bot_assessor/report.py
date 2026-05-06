from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def render_markdown(reviews: list[dict[str, Any]], *, generated_at: datetime, window_hours: int) -> str:
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Daily Bot Assessment - {stamp}",
        "",
        f"Window: last {window_hours} hours",
        "",
        "## Fleet Summary",
        "",
        "| Bot | Health | Commit | Trades | PnL | PF | Key issues |",
        "| --- | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for review in reviews:
        bt = review.get("backtest", {})
        logs = review.get("logs", {})
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
            "| {bot} | {score} {state} | `{commit}` | {trades} | {pnl} | {pf} | {issues} |".format(
                bot=review.get("bot_name"),
                score=review.get("health", {}).get("score"),
                state=review.get("health", {}).get("state"),
                commit=review.get("production", {}).get("short_commit"),
                trades=_fmt(bt.get("total_trades")),
                pnl=_fmt(bt.get("total_pnl")),
                pf=_fmt(bt.get("profit_factor")),
                issues=", ".join(issues),
            )
        )
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
    lines = [
        "",
        f"## {review.get('bot_name')}",
        "",
        f"Production: `{review.get('production', {}).get('short_commit')}` - {review.get('production', {}).get('commit_message')}",
        f"Health: {review.get('health', {}).get('score')} ({review.get('health', {}).get('state')})",
        f"Backtest: trades={_fmt(bt.get('total_trades'))}, pnl={_fmt(bt.get('total_pnl'))}, pf={_fmt(bt.get('profit_factor'))}, max_dd={_fmt_pct(bt.get('max_drawdown'))}",
        f"Logs: errors={logs.get('errors')}, warnings={logs.get('warnings')}, no_fills={logs.get('order_not_filled')}, missed={logs.get('missed_opportunity_count')}",
        "",
        "Recommendations:",
    ]
    for item in review.get("recommendations", []):
        lines.append(f"- **{item.get('severity', 'info').upper()}** {item.get('title')}: {item.get('action')}")
    overlays = review.get("parameter_overlays", [])
    if overlays:
        lines.append("")
        lines.append(f"Parameter overlays prepared: {len(overlays)}")
    noteworthy = logs.get("noteworthy_lines") or []
    if noteworthy:
        lines.append("")
        lines.append("Noteworthy log lines:")
        for line in noteworthy[:5]:
            lines.append(f"- `{line[:180]}`")
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