from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace

from bot_assessor.config import AssessorConfig, RuntimeOptions
from bot_assessor.heartbeat import send_fleet_heartbeat
from bot_assessor.optimizer import WeeklyOptimizer
from bot_assessor.orchestrator import BotAssessor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bot-assessor")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="Run the daily assessment")
    run.add_argument("--config", default=None)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--skip-backtests", action="store_true")
    run.add_argument("--skip-logs", action="store_true")
    optimize = sub.add_parser("optimize", help="Run the weekly PR-generating optimizer")
    optimize.add_argument("--config", default=None)
    optimize.add_argument("--bot", action="append", default=[])
    optimize.add_argument("--dry-run", action="store_true")
    optimize.add_argument("--skip-backtests", action="store_true")
    optimize.add_argument("--skip-tests", action="store_true")
    optimize.add_argument("--allow-auto-merge", action="store_true")
    heartbeat = sub.add_parser("heartbeat", help="Send the 6-hour fleet Telegram heartbeat")
    heartbeat.add_argument("--dry-run", action="store_true")
    heartbeat.add_argument("--force", action="store_true")
    validate = sub.add_parser("validate-config", help="Load and print config summary")
    validate.add_argument("--config", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"
    if command == "validate-config":
        config = AssessorConfig.load(args.config)
        print(json.dumps({"github_repo": config.github_repo, "bots": [bot.id for bot in config.bots]}, indent=2))
        return 0
    if command == "optimize":
        config = AssessorConfig.load(args.config)
        if args.bot:
            requested = set(args.bot)
            config = replace(config, bots=[bot for bot in config.bots if bot.id in requested])
        options = RuntimeOptions.from_env(
            dry_run=args.dry_run,
            skip_backtests=args.skip_backtests,
            skip_tests=args.skip_tests,
            allow_auto_merge=args.allow_auto_merge,
        )
        result = WeeklyOptimizer(config, options).run()
        print(
            json.dumps(
                {
                    "artifacts": result.artifacts,
                    "summary_issue": asdict(result.summary_issue),
                    "results": [asdict(item) for item in result.results],
                },
                indent=2,
                default=str,
            )
        )
        failed = [item for item in result.results if item.status == "failed"]
        if failed or not result.summary_issue.ok:
            return 1
        return 0
    if command == "heartbeat":
        result = send_fleet_heartbeat(dry_run=args.dry_run, force=args.force)
        print(json.dumps({"telegram": asdict(result)}, indent=2, default=str))
        return 0 if result.ok else 1
    config = AssessorConfig.load(args.config)
    options = RuntimeOptions.from_env(dry_run=args.dry_run, skip_backtests=args.skip_backtests, skip_logs=args.skip_logs)
    result = BotAssessor(config, options).run()
    print(json.dumps({"artifacts": result.artifacts, "github": asdict(result.github), "telegram": asdict(result.telegram), "redis_errors": result.redis_errors}, indent=2))
    if not result.github.ok or not result.telegram.ok or result.redis_errors:
        return 1
    return 0