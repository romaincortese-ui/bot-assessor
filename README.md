# Bot Assessor

Standalone daily assessment service for the trading bot fleet.

The service implements phases 1, 2, and 3 of the automation plan:

1. Collect production context from Railway logs and current GitHub code.
2. Build normalized daily review payloads for every configured bot.
3. Publish bounded, parameter-only overlay payloads to Redis when explicitly enabled.

It does **not** edit trading bot code or deploy bot changes. Code-changing optimizers should run as a separate, gated weekly PR workflow.

## What It Does

For each bot in `assessor_config.example.json`, the assessor:

- clones or updates the production GitHub repository
- reads current git commit metadata
- collects recent Railway logs using the Railway CLI
- runs the configured rolling backtest / calibration command
- parses errors, skipped signals, no-fills, stale data, missed opportunities, and backtest results
- writes a normalized JSON daily review per bot
- writes a combined Markdown report
- publishes the combined report as a GitHub issue
- sends a short Telegram message: `New daily report ready: <link>`
- optionally publishes review and overlay JSON to Redis

## Required Variables

Set these in the `bot-assessor` Railway service:

- `BOT_ASSESSOR_GITHUB_TOKEN`: GitHub token with permission to create issues in `romaincortese-ui/bot-assessor`
- `BOT_ASSESSOR_GITHUB_REPO=romaincortese-ui/bot-assessor`
- `RAILWAY_TOKEN`: token used by the Railway CLI to read logs

Telegram notification variables, added at the end after coding/deploying:

- `BOT_ASSESSOR_TELEGRAM_TOKEN`
- `BOT_ASSESSOR_TELEGRAM_CHAT_ID`

Optional Redis variables:

- `REDIS_URL`: Redis connection string from the shared Redis project
- `BOT_ASSESSOR_PUBLISH_COMPAT_REVIEWS=true`: publish each normalized review to the bot's compatible review key
- `BOT_ASSESSOR_APPLY_OVERLAYS=true`: publish safe overlay payloads to the configured overlay keys

Safety defaults:

- GitHub issue publishing is enabled when `BOT_ASSESSOR_GITHUB_TOKEN` exists.
- Telegram is skipped unless both Telegram variables exist.
- Redis publishing is skipped unless `REDIS_URL` exists.
- Overlay publishing is skipped unless `BOT_ASSESSOR_APPLY_OVERLAYS=true`.
- Research bots, currently Commodities and Bonds, have overlays disabled in config.

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy assessor_config.example.json assessor_config.json
python -m bot_assessor run --dry-run
```

Dry-run mode writes artifacts locally and skips GitHub issue creation, Telegram send, and Redis writes.

## Railway Deployment

This repo includes a Dockerfile that installs Python, Git, Node, and `@railway/cli`, then runs:

```bash
bot-assessor run
```

`railway.toml` schedules it daily at `06:00 UTC`:

```toml
cronSchedule = "0 6 * * *"
```

## Configuration

Copy `assessor_config.example.json` to `assessor_config.json` if you need to customize services or commands. By default the config covers:

- Mexc-v2 spot bot
- Futures bot
- Forex bot
- Gold bot
- Commodities bot
- Bonds bot

Each bot supports:

- `github_repo`: source repository to clone/pull
- `railway_service`: Railway service name for logs
- `backtest_command`: command run inside the cloned repo
- `backtest_env`: per-command environment overrides
- `compatible_review_redis_key`: optional normalized daily-review Redis key
- `overlay_redis_key`: optional parameter-overlay Redis key
- `allow_parameter_overlays`: whether safe overlays may be published

## Tests

```powershell
pytest
```

The tests cover log parsing, backtest parsing, recommendation generation, report rendering, GitHub/Telegram publishing behavior, Redis overlay safety, and the orchestrator dry-run path.