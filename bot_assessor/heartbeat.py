from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot_assessor.publishers import PublicationResult, TelegramNotifier

DEFAULT_HEARTBEAT_SECONDS = 6 * 60 * 60
LAST_SENT_REDIS_KEY = "bot_assessor:fleet_heartbeat:last_sent"
DEFAULT_STATE_FILE = "artifacts/fleet_heartbeat_state.json"


@dataclass(frozen=True)
class HeartbeatSource:
    id: str
    label: str
    emoji: str
    currency: str
    redis_keys: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BotMetrics:
    source: HeartbeatSource
    pnl_pct: float | None = None
    pnl_amount: float | None = None
    available_balance: float | None = None
    allocated_balance: float | None = None
    source_ref: str | None = None


DEFAULT_SOURCES = [
    HeartbeatSource("bonds", "Bonds bot", "🏦", "£", ["bonds_runtime_state", "bot_assessor:bonds:runtime_state", "bot_assessor:bonds:daily_review"]),
    HeartbeatSource("gold", "Gold bot", "🥇", "£", ["gold_bot_runtime_status", "gold_runtime_state", "bot_assessor:gold:daily_review"]),
    HeartbeatSource("forex", "FX bot", "💱", "£", ["bot_runtime_status", "fx_bot_runtime_status", "forex_bot_runtime_status", "bot_assessor:forex:daily_review"]),
    HeartbeatSource("futures", "Futures bot", "📈", "$", ["futures_runtime_status", "mexc_futures_runtime_state", "bot_assessor:mexc_futures:daily_review", "mexc_futures_daily_review"]),
    HeartbeatSource("commodities", "Commodities bot", "🌾", "£", ["commodities_runtime_state", "bot_assessor:commodities:runtime_state", "bot_assessor:commodities:daily_review"]),
    HeartbeatSource("mexc_spot", "MEXC Spot bot", "🟢", "$", ["mexc_bot_runtime_status", "mexc_runtime_state", "bot_assessor:mexc_spot:daily_review", "mexc_daily_review"]),
    HeartbeatSource("indices", "Indices bot", "📊", "£", ["indices_runtime_state", "indices_bot_runtime_status", "bot_assessor:indices:daily_review"]),
]


def load_sources() -> list[HeartbeatSource]:
    raw = os.getenv("BOT_ASSESSOR_HEARTBEAT_SOURCES", "").strip()
    if not raw:
        return DEFAULT_SOURCES
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("BOT_ASSESSOR_HEARTBEAT_SOURCES must be a JSON list")
    sources: list[HeartbeatSource] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        sources.append(
            HeartbeatSource(
                id=str(item.get("id") or item.get("label") or "bot"),
                label=str(item.get("label") or item.get("name") or item.get("id") or "Bot"),
                emoji=str(item.get("emoji") or "🤖"),
                currency=str(item.get("currency") or "£"),
                redis_keys=[str(key) for key in item.get("redis_keys", []) if key],
                file_paths=[str(path) for path in item.get("file_paths", []) if path],
            )
        )
    return sources or DEFAULT_SOURCES


class MetricsReader:
    def __init__(self, *, redis_url: str | None = None) -> None:
        self.redis_url = redis_url or os.getenv("REDIS_URL", "").strip()

    def read_source(self, source: HeartbeatSource) -> BotMetrics:
        for key in source.redis_keys:
            payload = self._read_redis_json(key)
            if isinstance(payload, dict):
                return metrics_from_payload(source, payload, source_ref=f"redis:{key}")
        for file_path in source.file_paths:
            payload = self._read_file_json(file_path)
            if isinstance(payload, dict):
                return metrics_from_payload(source, payload, source_ref=file_path)
        return BotMetrics(source=source)

    def last_sent_at(self) -> float:
        payload = self._read_redis_json(LAST_SENT_REDIS_KEY)
        if isinstance(payload, dict):
            value = _float_or_none(payload.get("last_sent_at"))
            if value is not None:
                return value
        path = Path(os.getenv("BOT_ASSESSOR_HEARTBEAT_STATE_FILE", DEFAULT_STATE_FILE))
        payload = self._read_file_json(str(path))
        if isinstance(payload, dict):
            value = _float_or_none(payload.get("last_sent_at"))
            if value is not None:
                return value
        return 0.0

    def record_sent_at(self, sent_at: float) -> None:
        payload = {"last_sent_at": sent_at, "last_sent_time": datetime.fromtimestamp(sent_at, timezone.utc).isoformat()}
        if self.redis_url:
            try:
                import redis

                client = redis.from_url(self.redis_url, socket_connect_timeout=10, socket_timeout=10)
                client.set(LAST_SENT_REDIS_KEY, json.dumps(payload), ex=14 * 24 * 3600)
                return
            except Exception:
                pass
        path = Path(os.getenv("BOT_ASSESSOR_HEARTBEAT_STATE_FILE", DEFAULT_STATE_FILE))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            return

    def _read_redis_json(self, key: str) -> dict[str, Any] | None:
        if not self.redis_url or not key:
            return None
        try:
            import redis

            client = redis.from_url(self.redis_url, socket_connect_timeout=10, socket_timeout=10)
            raw = client.get(key)
        except Exception:
            return None
        return _decode_json(raw)

    @staticmethod
    def _read_file_json(path_text: str) -> dict[str, Any] | None:
        path = Path(path_text)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


def metrics_from_payload(source: HeartbeatSource, payload: dict[str, Any], *, source_ref: str | None = None) -> BotMetrics:
    flattened = list(_walk_dicts(payload, descend_lists=False))
    pnl_amount = _first_number(flattened, ["session_pnl_amount", "total_pnl_amount", "total_pnl", "pnl", "daily_pnl", "unrealized_pl", "unrealizedPL"])
    pnl_pct = _first_number(flattened, ["session_pnl_pct", "total_pnl_pct", "pnl_pct", "return_pct", "daily_pnl_pct", "unrealized_pnl_pct"])
    available = _first_number(flattened, ["available_balance", "available", "margin_available", "marginAvailable", "free_balance", "cash", "balance_available"])
    allocated = _first_number(flattened, ["allocated_balance", "allocated", "margin_used", "marginUsed", "used_margin", "open_margin", "total_open_margin", "risk_allocated"])
    open_rows = _first_list(payload, ["open_positions", "open_trades", "positions", "trades"])
    if allocated is None and open_rows:
        allocated = _sum_position_values(open_rows, ["entry_budget", "allocated", "margin_used", "marginUsed", "initial_margin_required", "initialMarginRequired", "risk_amount", "current_value"])
    if pnl_amount is None and open_rows:
        pnl_amount = _sum_position_values(open_rows, ["unrealized_pl", "unrealizedPL", "pnl", "profit_loss"])
    if pnl_pct is None and pnl_amount is not None:
        base = allocated or available or _first_number(flattened, ["equity", "nav", "NAV", "balance"])
        if base and base > 0:
            pnl_pct = pnl_amount / base * 100.0
    return BotMetrics(source=source, pnl_pct=pnl_pct, pnl_amount=pnl_amount, available_balance=available, allocated_balance=allocated, source_ref=source_ref)


def build_heartbeat_message(metrics: list[BotMetrics], *, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    lines = [
        "💓 Fleet Heartbeat",
        f"🕒 {generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    for item in metrics:
        currency = item.source.currency
        lines.append(
            f"{item.source.emoji} {item.source.label}: "
            f"P&L {_format_pct(item.pnl_pct)}, {_format_signed_money(item.pnl_amount, currency)} | "
            f"Av.Balance: {_format_money(item.available_balance, currency)} | "
            f"Allocated: {_format_money(item.allocated_balance, currency)}"
        )
    return "\n".join(lines)


def send_fleet_heartbeat(*, telegram: TelegramNotifier | None = None, reader: MetricsReader | None = None, dry_run: bool = False, force: bool = False) -> PublicationResult:
    reader = reader or MetricsReader()
    interval = max(0, int(os.getenv("BOT_ASSESSOR_HEARTBEAT_SECONDS", str(DEFAULT_HEARTBEAT_SECONDS))))
    now_ts = datetime.now(timezone.utc).timestamp()
    if not force and interval > 0 and now_ts - reader.last_sent_at() < interval:
        return PublicationResult(ok=True, skipped=True, metadata={"reason": "heartbeat_interval_not_elapsed"})
    metrics = [reader.read_source(source) for source in load_sources()]
    message = build_heartbeat_message(metrics)
    notifier = telegram or TelegramNotifier()
    result = notifier.send_message(message, dry_run=dry_run)
    if result.ok and not result.skipped:
        reader.record_sent_at(now_ts)
    return PublicationResult(ok=result.ok, skipped=result.skipped, error=result.error, metadata={"message": message, "metrics": [metric_to_dict(item) for item in metrics]})


def metric_to_dict(item: BotMetrics) -> dict[str, Any]:
    return {
        "id": item.source.id,
        "label": item.source.label,
        "pnl_pct": item.pnl_pct,
        "pnl_amount": item.pnl_amount,
        "available_balance": item.available_balance,
        "allocated_balance": item.allocated_balance,
        "source_ref": item.source_ref,
    }


def _walk_dicts(value: Any, *, descend_lists: bool = True) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child, descend_lists=descend_lists))
    elif descend_lists and isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child, descend_lists=descend_lists))
    return found


def _first_number(dicts: list[dict[str, Any]], keys: list[str]) -> float | None:
    for mapping in dicts:
        for key in keys:
            value = _float_or_none(mapping.get(key))
            if value is not None:
                return value
    return None


def _first_list(payload: dict[str, Any], keys: list[str]) -> list[Any]:
    for mapping in _walk_dicts(payload):
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, list):
                return value
    return []


def _sum_position_values(rows: list[Any], keys: list[str]) -> float | None:
    total = 0.0
    seen = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in keys:
            value = _float_or_none(row.get(key))
            if value is not None:
                total += value
                seen = True
                break
    return total if seen else None


def _decode_json(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _format_money(value: float | None, currency: str) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}{currency}{abs(value):,.2f}"


def _format_signed_money(value: float | None, currency: str) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else "-"
    return f"{sign}{currency}{abs(value):,.2f}"
