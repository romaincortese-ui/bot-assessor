from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field


_SYMBOL_RE = re.compile(r"\bsymbol=([^\s]+)", re.IGNORECASE)
_BLOCKED_BY_RE = re.compile(r"\bblocked_by=([^\s]+)", re.IGNORECASE)


@dataclass(frozen=True)
class MissedOpportunity:
    line: str
    symbol: str | None = None
    blocked_by: str | None = None


@dataclass(frozen=True)
class LogAnalysis:
    total_lines: int
    errors: int
    warnings: int
    order_opened: int
    order_closed: int
    order_not_filled: int
    skip_events: int
    stale_data_hits: int
    missed_opportunities: list[MissedOpportunity] = field(default_factory=list)
    top_blockers: list[tuple[str, int]] = field(default_factory=list)
    noteworthy_lines: list[str] = field(default_factory=list)


def analyze_logs(text: str, *, max_noteworthy: int = 20) -> LogAnalysis:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    errors = warnings = opened = closed = no_fill = skips = stale = 0
    missed: list[MissedOpportunity] = []
    blockers: Counter[str] = Counter()
    noteworthy: list[str] = []
    for line in lines:
        lowered = line.lower()
        is_noteworthy = False
        if "traceback" in lowered or "error" in lowered or "exception" in lowered or "failed" in lowered:
            errors += 1
            is_noteworthy = True
        if "warning" in lowered or "warn" in lowered:
            warnings += 1
            is_noteworthy = True
        if "trade_opened" in lowered or "order opened" in lowered or "position opened" in lowered or "entry" in lowered and "opened" in lowered:
            opened += 1
        if "trade_closed" in lowered or "position closed" in lowered or "exit" in lowered and "closed" in lowered:
            closed += 1
        if "not filled" in lowered or "order_not_filled" in lowered or "reject" in lowered or "insufficient_margin" in lowered:
            no_fill += 1
            is_noteworthy = True
        if "skip_reason" in lowered or "skipping" in lowered or "no_signal" in lowered:
            skips += 1
        if "stale" in lowered or "no_fresh" in lowered or "missing_candles" in lowered or "missing" in lowered and "state" in lowered:
            stale += 1
            is_noteworthy = True
        if "missed_opportunity" in lowered:
            symbol_match = _SYMBOL_RE.search(line)
            blocker_match = _BLOCKED_BY_RE.search(line)
            symbol = symbol_match.group(1) if symbol_match else None
            blocked_by = blocker_match.group(1) if blocker_match else None
            missed.append(MissedOpportunity(line=line[:500], symbol=symbol, blocked_by=blocked_by))
            if blocked_by:
                blockers[blocked_by] += 1
            is_noteworthy = True
        if is_noteworthy and len(noteworthy) < max_noteworthy:
            noteworthy.append(line[:500])
    return LogAnalysis(
        total_lines=len(lines),
        errors=errors,
        warnings=warnings,
        order_opened=opened,
        order_closed=closed,
        order_not_filled=no_fill,
        skip_events=skips,
        stale_data_hits=stale,
        missed_opportunities=missed,
        top_blockers=blockers.most_common(10),
        noteworthy_lines=noteworthy,
    )