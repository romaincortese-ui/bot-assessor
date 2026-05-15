# Bot Assessor

Standalone assessment and gated improvement service for the trading bot fleet.

The service implements phases 1 through 5 of the automation plan:

1. Collect production context from Railway deployment status, Railway logs, fallback runtime status sources, and current GitHub code.
2. Build normalized daily review payloads for every configured bot.
3. Publish bounded, parameter-only overlay payloads to Redis when explicitly enabled.
4. Run a weekly PR-generating optimizer that creates candidate branches, runs tests, compares baseline/candidate backtests, and opens PRs.
5. Allow limited auto-merge only when global and per-bot gates are enabled and changed files match a strict allowlist.

Daily runs do **not** edit trading bot code or deploy bot changes. Weekly optimizer runs can open PRs only after an explicit per-bot `optimizer_command` creates a candidate patch.

## What It Does

For each bot in `assessor_config.example.json`, the assessor:

- clones or updates the production GitHub repository
- runs each bot's configured setup command, usually `pip install -r requirements.txt`
- reads current git commit metadata
- verifies the latest Railway deployment status when the Railway CLI can access the service
- collects recent Railway logs using chunked Railway CLI calls when large windows are requested
- falls back to configured runtime status files or Redis keys if Railway logs are unavailable
- runs the configured rolling backtest / calibration command
- parses errors, skipped signals, no-fills, stale data, missed opportunities, and backtest results
- writes a normalized JSON daily review per bot
- writes a combined Markdown report
- publishes the combined report as a GitHub issue
- sends a short Telegram message: `New daily report ready: <link>`
- optionally publishes review and overlay JSON to Redis
- prepares explicit, approval-required Railway variable change plans when a bot has allowlisted variables and mappings configured

The weekly optimizer:

- creates a fresh candidate branch in each enabled bot repo
- runs the configured `optimizer_command` inside the bot repo
- runs full tests when `test_command` is configured
- runs baseline and candidate backtests across configured scenarios
- enforces guardrails such as minimum trades, PnL improvement, profit-factor quality, and drawdown limits
- opens a GitHub PR in the bot repo with the report in the PR body
- optionally auto-merges only when `BOT_ASSESSOR_ALLOW_AUTO_MERGE=true`, `auto_merge_enabled=true`, guardrails pass, and every changed file matches `auto_merge_allowed_file_patterns`

## Required Variables

Set these in the `bot-assessor` Railway service:

- `BOT_ASSESSOR_GITHUB_TOKEN`: GitHub token with permission to create issues in `romaincortese-ui/bot-assessor`
- `BOT_ASSESSOR_GITHUB_REPO=romaincortese-ui/bot-assessor`
- `RAILWAY_TOKEN`: token used by the Railway CLI to read logs
- For phase 4/5 PR creation across bot repos, `BOT_ASSESSOR_GITHUB_TOKEN` must also be able to push branches and open pull requests in each target bot repository.

See `.env.example` for the full variable list.

Telegram notification variables, added at the end after coding/deploying:

- `BOT_ASSESSOR_TELEGRAM_TOKEN`
- `BOT_ASSESSOR_TELEGRAM_CHAT_ID`
- `BOT_ASSESSOR_HEARTBEAT_SECONDS=21600`: minimum interval for the fleet heartbeat command.
- `BOT_ASSESSOR_HEARTBEAT_SOURCES`: optional JSON list for overriding Redis/file metric sources.

Optional Redis variables:

- `REDIS_URL`: Redis connection string from the shared Redis project
- `BOT_ASSESSOR_PUBLISH_COMPAT_REVIEWS=true`: publish each normalized review to the bot's compatible review key
- `BOT_ASSESSOR_APPLY_OVERLAYS=true`: publish safe overlay payloads to the configured overlay keys
- `BOT_ASSESSOR_ALLOW_AUTO_MERGE=true`: allow phase 5 auto-merge for bots that also set `auto_merge_enabled=true`

Railway variable changes are proposal-only by default. To make a variable eligible for future automation, add it to `managed_railway_variables` and map a specific overlay key such as `score_offset:global` in `railway_variable_mappings`. The daily report records proposed and blocked changes, but the assessor does not freely mutate Railway variables.

Safety defaults:

- GitHub issue publishing is enabled when `BOT_ASSESSOR_GITHUB_TOKEN` exists.
- Telegram is skipped unless both Telegram variables exist.
- Redis publishing is skipped unless `REDIS_URL` exists.
- Overlay publishing is skipped unless `BOT_ASSESSOR_APPLY_OVERLAYS=true`.
- Research bots, currently Commodities and Bonds, have overlays disabled in config.
- Weekly auto-merge is skipped unless both the global variable and per-bot config allow it.
- Forex and Gold are configured for manual PR approval only.
- Commodities and Bonds have the weekly optimizer disabled until their data/research foundations are stronger.

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy assessor_config.example.json assessor_config.json
python -m bot_assessor run --dry-run
python -m bot_assessor optimize --dry-run
python -m bot_assessor heartbeat --dry-run --force
```

Dry-run mode writes artifacts locally and skips GitHub issue creation, Telegram send, and Redis writes.
For the weekly optimizer, dry-run mode still runs local checks but skips branch push, PR creation, and auto-merge.
The `heartbeat` command builds one concise fleet Telegram message from Redis/runtime-state metrics every 6 hours by default.

## Railway Deployment

This repo includes a Dockerfile that installs Python, Git, Node, and `@railway/cli`, then runs:

```bash
bot-assessor run
```

`railway.toml` schedules it daily at `06:00 UTC`:

```toml
cronSchedule = "0 6 * * *"
```

This repo also includes GitHub Actions workflows:

- `daily-assessment.yml`: daily assessment at `06:00 UTC`
- `fleet-heartbeat.yml`: fleet P&L/balance heartbeat every 6 hours
- `weekly-optimizer.yml`: weekly optimizer at `07:00 UTC` on Mondays

## Configuration

Copy `assessor_config.example.json` to `assessor_config.json` if you need to customize services or commands. By default the config covers:

- Mexc-v2 spot bot
- Futures bot
- Forex bot
- Gold bot
- Indices bot
- Commodities bot
- Bonds bot

Each bot supports:

- `github_repo`: source repository to clone/pull
- `railway_service`: Railway service name for logs
- `railway_project_id`: optional Railway project id used when a service name alone is not enough for the CLI
- `railway_environment_id`: optional Railway environment id used instead of the environment name
- `backtest_command`: command run inside the cloned repo
- `setup_command`: optional dependency/setup command run before the backtest
- `backtest_env`: per-command environment overrides
- `compatible_review_redis_key`: optional normalized daily-review Redis key
- `overlay_redis_key`: optional parameter-overlay Redis key
- `runtime_status_files`: optional fallback files to read when Railway logs are unavailable
- `daily_review_files`: optional fallback review files to read when Railway logs are unavailable
- `runtime_status_redis_keys`: optional fallback Redis keys to read when Railway logs are unavailable
- `managed_railway_variables`: strict allowlist of Railway variables the assessor may propose changing
- `railway_variable_mappings`: mapping from overlay keys such as `threshold_adjustment:score_threshold` to managed Railway variables
- `allow_parameter_overlays`: whether safe overlays may be published
- `optimizer_enabled`: whether the weekly optimizer should consider the bot
- `optimizer_command`: the bot-specific agent/script command that edits the candidate branch
- `optimizer_backtests`: named baseline/candidate backtest scenarios, usually 30/60/90-day windows
- `optimizer_guardrails`: pass/fail rules for tests and candidate performance
- `allowed_pr_file_patterns`: optional file allowlist for PR generation
- `auto_merge_enabled`: per-bot phase 5 auto-merge gate
- `auto_merge_allowed_file_patterns`: stricter file allowlist for phase 5 auto-merge

The example config enables weekly optimizer consideration for Spot, Futures, Forex, Gold, and Indices, but leaves `optimizer_command` empty. Add a bot-specific command only after that bot has a deterministic patch generator or agent workflow. Commodities and Bonds remain assessment-only.

## Weekly Optimizer

```powershell
python -m bot_assessor optimize --dry-run
python -m bot_assessor optimize --bot mexc_spot
```

Recommended rollout:

1. Add `optimizer_command` for one mature bot.
2. Run `optimize --dry-run --bot <id>` until the generated patch, tests, and backtests look sane.
3. Run without dry-run to open manual-review PRs.
4. Only after several clean weekly PRs, set `BOT_ASSESSOR_ALLOW_AUTO_MERGE=true` and keep auto-merge limited to JSON/config/calibration files.

## Solution Designs

- [docs/indices-bot-solution-design.md](docs/indices-bot-solution-design.md): AI-agent-ready specification for a new OANDA indices trading bot.

## Tests

```powershell
pytest
```

The tests cover log parsing, Railway status/log collection, backtest parsing, recommendation generation, report rendering, GitHub/Telegram publishing behavior, Redis overlay safety, and the orchestrator dry-run path.