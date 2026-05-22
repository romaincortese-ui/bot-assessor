from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from bot_assessor.backtest import BacktestResult
from bot_assessor.config import BotConfig
from bot_assessor.logs import LogAnalysis


@dataclass(frozen=True)
class PortfolioSummary:
    bot_id: str
    bot_name: str
    currency: str
    state: str
    decision: str
    live_pnl_amount: float | None = None
    live_pnl_pct_nav: float | None = None
    backtest_pnl: float | None = None
    backtest_return_pct: float | None = None
    profit_factor: float | None = None
    win_rate: float | None = None
    max_drawdown: float | None = None
    total_trades: int | None = None
    open_positions: int | None = None
    nav: float | None = None
    margin_used: float | None = None
    margin_used_pct_nav: float | None = None
    risk_at_stop: float | None = None
    risk_at_stop_pct_nav: float | None = None
    exposure_notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_portfolio_summary(
    bot: BotConfig,
    *,
    logs: LogAnalysis,
    backtest: BacktestResult | None,
    runtime_status: dict[str, Any] | None,
) -> PortfolioSummary:
    payloads = runtime_status.get("payloads", {}) if isinstance(runtime_status, dict) else {}
    flattened = list(_walk_dicts(payloads))
    open_rows = _first_list(payloads, ["open_positions", "open_trades", "positions", "trades"])
    nav = _first_number(
        flattened,
        ["account_nav", "nav", "NAV", "equity", "account_balance", "balance", "available_balance", "cash", "free_balance"],
    )
    margin_used = _first_number(
        flattened,
        ["account_margin_used", "margin_used", "marginUsed", "used_margin", "open_margin", "total_open_margin", "allocated_balance", "allocated"],
    )
    if margin_used is None:
        margin_used = _sum_position_values(open_rows, ["margin_used", "marginUsed", "entry_budget", "initial_margin_required", "allocated", "current_value"])
    risk_at_stop = _first_number(flattened, ["total_risk_at_stop", "risk_at_stop", "open_risk", "open_risk_usdt", "risk_allocated"])
    if risk_at_stop is None:
        risk_at_stop = _sum_position_risk(open_rows)
    live_pnl_amount = _first_number(
        flattened,
        ["session_pnl_amount", "daily_pnl", "realized_pl", "unrealized_pl", "unrealizedPL", "account_unrealized_pl", "pnl_amount", "total_pnl_amount"],
    )
    if live_pnl_amount is None:
        live_pnl_amount = _sum_position_values(open_rows, ["unrealized_pl", "unrealizedPL", "pnl", "profit_loss"])
    live_pnl_pct_nav = _first_number(flattened, ["session_pnl_pct", "daily_pnl_pct", "unrealized_pnl_pct", "pnl_pct"])
    if live_pnl_pct_nav is None and live_pnl_amount is not None and nav and nav > 0:
        live_pnl_pct_nav = live_pnl_amount / nav * 100.0
    margin_used_pct_nav = margin_used / nav * 100.0 if margin_used is not None and nav and nav > 0 else None
    risk_at_stop_pct_nav = risk_at_stop / nav * 100.0 if risk_at_stop is not None and nav and nav > 0 else None
    open_positions = len(open_rows) if open_rows else _as_int(_first_number(flattened, ["open_position_count", "open_positions_count", "open_trades_count"]))
    exposure_notes = _exposure_notes(
        logs=logs,
        backtest=backtest,
        nav=nav,
        margin_used_pct_nav=margin_used_pct_nav,
        risk_at_stop_pct_nav=risk_at_stop_pct_nav,
        live_pnl_amount=live_pnl_amount,
        open_positions=open_positions,
    )
    decision = _decision(logs=logs, backtest=backtest, exposure_notes=exposure_notes)
    return PortfolioSummary(
        bot_id=bot.id,
        bot_name=bot.name,
        currency=_currency_for(bot),
        state=_portfolio_state(logs, backtest, exposure_notes),
        decision=decision,
        live_pnl_amount=live_pnl_amount,
        live_pnl_pct_nav=live_pnl_pct_nav,
        backtest_pnl=backtest.total_pnl if backtest else None,
        backtest_return_pct=backtest.return_pct if backtest else None,
        profit_factor=backtest.profit_factor if backtest else None,
        win_rate=backtest.win_rate if backtest else None,
        max_drawdown=backtest.max_drawdown if backtest else None,
        total_trades=backtest.total_trades if backtest else None,
        open_positions=open_positions,
        nav=nav,
        margin_used=margin_used,
        margin_used_pct_nav=margin_used_pct_nav,
        risk_at_stop=risk_at_stop,
        risk_at_stop_pct_nav=risk_at_stop_pct_nav,
        exposure_notes=exposure_notes,
    )


def fleet_rollup(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    by_currency: dict[str, dict[str, float]] = {}
    attention: list[str] = []
    best: dict[str, Any] | None = None
    worst: dict[str, Any] | None = None
    for review in reviews:
        portfolio = review.get("portfolio") or {}
        currency = str(portfolio.get("currency") or "?")
        bucket = by_currency.setdefault(currency, {"live_pnl_amount": 0.0, "risk_at_stop": 0.0, "margin_used": 0.0})
        for key in ("live_pnl_amount", "risk_at_stop", "margin_used"):
            value = _as_float(portfolio.get(key))
            if value is not None:
                bucket[key] += value
        if portfolio.get("state") in {"attention", "risk_reduction"}:
            attention.append(str(review.get("bot_name") or portfolio.get("bot_name") or review.get("bot_id")))
        pnl = _as_float(portfolio.get("backtest_pnl"))
        if pnl is not None:
            item = {"bot": review.get("bot_name"), "pnl": pnl, "currency": currency}
            if best is None or pnl > best["pnl"]:
                best = item
            if worst is None or pnl < worst["pnl"]:
                worst = item
    return {"by_currency": by_currency, "attention": attention, "best_backtest": best, "worst_backtest": worst}


def _currency_for(bot: BotConfig) -> str:
    lowered = f"{bot.id} {bot.name}".lower()
    if "mexc" in lowered or "futures" in lowered or "spot" in lowered:
        return "USD"
    return "GBP"


def _portfolio_state(logs: LogAnalysis, backtest: BacktestResult | None, exposure_notes: list[str]) -> str:
    if logs.errors or logs.order_not_filled or backtest is None or not backtest.ok:
        return "attention"
    if any("risk" in note.lower() or "margin" in note.lower() for note in exposure_notes):
        return "risk_reduction"
    if backtest.total_pnl is not None and backtest.total_pnl < 0:
        return "risk_reduction"
    return "healthy"


def _decision(logs: LogAnalysis, backtest: BacktestResult | None, exposure_notes: list[str]) -> str:
    if logs.errors or logs.order_not_filled or backtest is None or not backtest.ok:
        return "repair_before_optimizing"
    if backtest.total_trades == 0:
        return "increase_sample_before_changes"
    if backtest.total_pnl is not None and backtest.total_pnl < 0:
        return "tighten_risk_and_backtest_candidate"
    if exposure_notes:
        return "reduce_exposure_before_scaling"
    return "hold_or_test_incremental_improvements"


def _exposure_notes(
    *,
    logs: LogAnalysis,
    backtest: BacktestResult | None,
    nav: float | None,
    margin_used_pct_nav: float | None,
    risk_at_stop_pct_nav: float | None,
    live_pnl_amount: float | None,
    open_positions: int | None,
) -> list[str]:
    notes: list[str] = []
    if nav is None:
        notes.append("live NAV unavailable; account-risk normalization is incomplete")
    if margin_used_pct_nav is not None and margin_used_pct_nav > 30.0:
        notes.append(f"margin/collateral usage is high at {margin_used_pct_nav:.2f}% of NAV")
    if risk_at_stop_pct_nav is not None and risk_at_stop_pct_nav > 5.0:
        notes.append(f"open stop risk is high at {risk_at_stop_pct_nav:.2f}% of NAV")
    if live_pnl_amount is not None and live_pnl_amount < 0 and open_positions:
        notes.append("live open P&L is negative while positions remain open")
    if backtest is not None and backtest.total_pnl is not None and backtest.total_pnl < 0:
        notes.append("rolling backtest is negative")
    if backtest is not None and backtest.profit_factor is not None and backtest.profit_factor < 1.0:
        notes.append("profit factor is below 1.0")
    if logs.stale_data_hits:
        notes.append("stale data appeared in production logs")
    return notes


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child))
    return found


def _first_number(dicts: list[dict[str, Any]], keys: list[str]) -> float | None:
    for mapping in dicts:
        for key in keys:
            value = _as_float(mapping.get(key))
            if value is not None:
                return value
    return None


def _first_list(value: Any, keys: list[str]) -> list[Any]:
    for mapping in _walk_dicts(value):
        for key in keys:
            rows = mapping.get(key)
            if isinstance(rows, list):
                return rows
    return []


def _sum_position_values(rows: list[Any], keys: list[str]) -> float | None:
    total = 0.0
    seen = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in keys:
            value = _as_float(row.get(key))
            if value is not None:
                total += value
                seen = True
                break
    return total if seen else None


def _sum_position_risk(rows: list[Any]) -> float | None:
    total = 0.0
    seen = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        explicit = _as_float(row.get("risk_at_stop") or row.get("risk_amount") or row.get("stop_risk") or row.get("open_risk_usdt"))
        if explicit is not None and explicit > 0:
            total += explicit
            seen = True
            continue
        entry = _as_float(row.get("entry_price"))
        stop = _as_float(row.get("stop_price") or row.get("sl_price"))
        qty = _as_float(row.get("qty") or row.get("units") or row.get("base_qty") or row.get("contracts"))
        contract_size = _as_float(row.get("contract_size")) or 1.0
        if entry is not None and stop is not None and qty is not None and qty != 0:
            total += abs(entry - stop) * abs(qty) * contract_size
            seen = True
    return total if seen else None


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None