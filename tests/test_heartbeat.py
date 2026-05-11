from __future__ import annotations

from bot_assessor.heartbeat import BotMetrics, HeartbeatSource, build_heartbeat_message, metrics_from_payload, send_fleet_heartbeat
from bot_assessor.publishers import PublicationResult


class StubReader:
    def __init__(self, *, last_sent_at: float = 0.0) -> None:
        self.recorded: float | None = None
        self.last_sent = last_sent_at
        self.source = HeartbeatSource("bonds", "Bonds bot", "🏦", "£")

    def last_sent_at(self) -> float:
        return self.last_sent

    def read_source(self, source: HeartbeatSource) -> BotMetrics:
        return BotMetrics(source=source, pnl_pct=2.0, pnl_amount=5.0, available_balance=100.0, allocated_balance=60.0)

    def record_sent_at(self, sent_at: float) -> None:
        self.recorded = sent_at


class StubTelegram:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, text: str, *, dry_run: bool = False) -> PublicationResult:
        self.messages.append(text)
        return PublicationResult(ok=True)


def test_metrics_from_payload_extracts_and_computes_values() -> None:
    source = HeartbeatSource("bonds", "Bonds bot", "🏦", "£")
    payload = {
        "available_balance": 100.0,
        "open_positions": [
            {"entry_budget": 40.0, "unrealized_pl": 2.0},
            {"entry_budget": 20.0, "unrealized_pl": 3.0},
        ],
    }

    metrics = metrics_from_payload(source, payload, source_ref="test")

    assert metrics.pnl_pct == 5.0 / 60.0 * 100.0
    assert metrics.pnl_amount == 5.0
    assert metrics.available_balance == 100.0
    assert metrics.allocated_balance == 60.0


def test_build_heartbeat_message_is_clear_and_concise() -> None:
    source = HeartbeatSource("bonds", "Bonds bot", "🏦", "£")
    message = build_heartbeat_message([BotMetrics(source, pnl_pct=2.0, pnl_amount=5.0, available_balance=100.0, allocated_balance=60.0)])

    assert "💓 Fleet Heartbeat" in message
    assert "🏦 Bonds bot: P&L +2.00%, +£5.00 | Av.Balance: £100.00 | Allocated: £60.00" in message


def test_send_fleet_heartbeat_respects_interval(monkeypatch) -> None:
    monkeypatch.setenv("BOT_ASSESSOR_HEARTBEAT_SECONDS", "21600")
    reader = StubReader(last_sent_at=9999999999.0)

    result = send_fleet_heartbeat(reader=reader, telegram=StubTelegram(), force=False)

    assert result.ok is True
    assert result.skipped is True
    assert result.metadata["reason"] == "heartbeat_interval_not_elapsed"


def test_send_fleet_heartbeat_sends_and_records_when_forced(monkeypatch) -> None:
    monkeypatch.setenv("BOT_ASSESSOR_HEARTBEAT_SOURCES", '[{"id":"bonds","label":"Bonds bot","emoji":"🏦","currency":"£"}]')
    reader = StubReader()
    telegram = StubTelegram()

    result = send_fleet_heartbeat(reader=reader, telegram=telegram, force=True)

    assert result.ok is True
    assert telegram.messages
    assert "Bonds bot" in telegram.messages[0]
    assert reader.recorded is not None
