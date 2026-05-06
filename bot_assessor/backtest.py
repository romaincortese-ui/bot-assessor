from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot_assessor.command import CommandRunner
from bot_assessor.config import BotConfig


@dataclass(frozen=True)
class BacktestResult:
    ok: bool
    command: list[str]
    returncode: int | None
    raw_output: str
    total_trades: int | None = None
    total_pnl: float | None = None
    return_pct: float | None = None
    profit_factor: float | None = None
    win_rate: float | None = None
    max_drawdown: float | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None


class BacktestRunner:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def run(self, bot: BotConfig, *, repo_path: str | Path) -> BacktestResult:
        if not bot.backtest_command:
            return BacktestResult(False, [], None, "", error="No backtest_command configured")
        return self.run_command(
            bot.backtest_command,
            repo_path=repo_path,
            setup_command=bot.setup_command,
            env=bot.backtest_env,
        )

    def run_command(
        self,
        command: list[str],
        *,
        repo_path: str | Path,
        setup_command: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 3600,
    ) -> BacktestResult:
        if not command:
            return BacktestResult(False, [], None, "", error="No backtest_command configured")
        if setup_command:
            setup = self.runner.run(setup_command, cwd=repo_path, env=env, timeout_seconds=1800)
            if not setup.ok:
                return BacktestResult(
                    ok=False,
                    command=command,
                    returncode=setup.returncode,
                    raw_output=setup.combined_output[-12000:],
                    error=f"setup_command failed: {(setup.stderr or setup.stdout).strip()[-2000:]}",
                )
        result = self.runner.run(command, cwd=repo_path, env=env, timeout_seconds=timeout_seconds)
        parsed = parse_backtest_output(result.combined_output)
        return BacktestResult(
            ok=result.ok,
            command=command,
            returncode=result.returncode,
            raw_output=result.combined_output[-12000:],
            error=None if result.ok else (result.stderr.strip() or result.stdout.strip())[-2000:],
            **parsed,
        )


def parse_backtest_output(text: str) -> dict[str, Any]:
    payload = _parse_json_payload(text)
    if isinstance(payload, dict):
        summary = _find_summary(payload)
        return _metrics_from_summary(summary)
    return _metrics_from_text(text)


def _parse_json_payload(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(stripped[first : last + 1])
        except json.JSONDecodeError:
            return None
    return None


def _find_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("summary"), dict):
        return payload["summary"]
    if isinstance(payload.get("report"), dict):
        return payload["report"]
    if isinstance(payload.get("calibration"), dict) and isinstance(payload["calibration"].get("report"), dict):
        return payload["calibration"]["report"]
    return payload


def _metrics_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": summary,
        "total_trades": _as_int(summary.get("total_trades") or summary.get("trades")),
        "total_pnl": _as_float(summary.get("total_pnl") or summary.get("pnl")),
        "return_pct": _as_float(summary.get("return_pct") or summary.get("total_return_pct")),
        "profit_factor": _as_float(summary.get("profit_factor")),
        "win_rate": _as_float(summary.get("win_rate")),
        "max_drawdown": _as_float(summary.get("max_drawdown") or summary.get("max_drawdown_pct")),
    }


def _metrics_from_text(text: str) -> dict[str, Any]:
    trades = _match_int(text, r"trades=([0-9]+)")
    pnl = _match_float(text, r"pnl=([-+0-9.]+)")
    ret = _match_float(text, r"return=([-+0-9.]+)%")
    pf = _match_float(text, r"pf=([-+0-9.]+)")
    dd = _match_float(text, r"max_dd=([-+0-9.]+)%")
    win = _match_float(text, r"win_rate=([-+0-9.]+)%")
    return {
        "summary": {},
        "total_trades": trades,
        "total_pnl": pnl,
        "return_pct": ret / 100.0 if ret is not None else None,
        "profit_factor": pf,
        "win_rate": win / 100.0 if win is not None else None,
        "max_drawdown": dd / 100.0 if dd is not None else None,
    }


def _match_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return _as_float(match.group(1)) if match else None


def _match_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return _as_int(match.group(1)) if match else None


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