# Bot Assessor Workspace Instructions

- Keep this repository independent from the trading bot repositories.
- Prefer small, deterministic modules with tests over runtime-only scripts.
- Do not hard-code secrets. All tokens, Telegram settings, Redis URLs, and Railway access must come from environment variables.
- Treat automatic parameter overlays as opt-in and bounded. Code changes and deployments must stay outside the daily assessor loop.
- Weekly code-optimizer PRs are allowed only through the gated optimizer flow: candidate branch, tests, baseline/candidate backtests, PR report, and opt-in auto-merge allowlists.
- Reports should be published to GitHub issues; Telegram should only send a short notification with the report link.
- Maintain README and configuration examples when behavior changes.

Checklist status:

- [x] Clarified project requirements
- [x] Scaffolded standalone Python project
- [x] Implemented central assessment service
- [x] Added GitHub, Telegram, Redis, Railway-log, and overlay components
- [x] Added weekly PR optimizer and gated auto-merge controls
- [x] Added tests and documentation
- [x] Validated test suite
- [x] Initialized git and pushed to GitHub