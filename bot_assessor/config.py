from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BotConfig:
    id: str
    name: str
    github_repo: str
    repo_path: str | None = None
    default_branch: str = "main"
    railway_service: str | None = None
    railway_environment: str = "production"
    log_lines: int | None = None
    setup_command: list[str] = field(default_factory=list)
    backtest_command: list[str] = field(default_factory=list)
    backtest_env: dict[str, str] = field(default_factory=dict)
    test_command: list[str] = field(default_factory=list)
    runtime_status_files: list[str] = field(default_factory=list)
    daily_review_files: list[str] = field(default_factory=list)
    maturity: str = "research"
    compatible_review_redis_key: str | None = None
    overlay_redis_key: str | None = None
    allow_parameter_overlays: bool = False
    allowed_overlay_types: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, default_log_lines: int) -> "BotConfig":
        data = dict(raw)
        data.setdefault("log_lines", default_log_lines)
        return cls(**data)


@dataclass(frozen=True)
class AssessorConfig:
    github_repo: str
    artifact_dir: str = "artifacts"
    workdir: str = "workdir"
    window_hours: int = 24
    log_lines: int = 1200
    report_labels: list[str] = field(default_factory=lambda: ["daily-assessment", "bot-assessor"])
    bots: list[BotConfig] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AssessorConfig":
        config_path = Path(path or os.getenv("BOT_ASSESSOR_CONFIG", "assessor_config.json"))
        if not config_path.exists():
            config_path = Path("assessor_config.example.json")
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        default_log_lines = int(raw.get("log_lines", 1200))
        bots = [BotConfig.from_dict(item, default_log_lines=default_log_lines) for item in raw.get("bots", [])]
        return cls(
            github_repo=os.getenv("BOT_ASSESSOR_GITHUB_REPO", raw.get("github_repo", "")),
            artifact_dir=str(raw.get("artifact_dir", "artifacts")),
            workdir=str(raw.get("workdir", "workdir")),
            window_hours=int(os.getenv("BOT_ASSESSOR_WINDOW_HOURS", raw.get("window_hours", 24))),
            log_lines=default_log_lines,
            report_labels=list(raw.get("report_labels", ["daily-assessment", "bot-assessor"])),
            bots=bots,
        )


@dataclass(frozen=True)
class RuntimeOptions:
    dry_run: bool = False
    publish_compatible_reviews: bool = False
    apply_overlays: bool = False
    skip_backtests: bool = False
    skip_logs: bool = False

    @classmethod
    def from_env(cls, *, dry_run: bool = False, skip_backtests: bool = False, skip_logs: bool = False) -> "RuntimeOptions":
        return cls(
            dry_run=dry_run or _env_bool("BOT_ASSESSOR_DRY_RUN", False),
            publish_compatible_reviews=_env_bool("BOT_ASSESSOR_PUBLISH_COMPAT_REVIEWS", False),
            apply_overlays=_env_bool("BOT_ASSESSOR_APPLY_OVERLAYS", False),
            skip_backtests=skip_backtests or _env_bool("BOT_ASSESSOR_SKIP_BACKTESTS", False),
            skip_logs=skip_logs or _env_bool("BOT_ASSESSOR_SKIP_LOGS", False),
        )