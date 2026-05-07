# Indices Bot Solution Design

Audience: AI agent developer building a new repository for `indices-bot`.

Status: implementation specification.

Goal: build a standalone OANDA-integrated trading bot for stock indices that follows the efficient architecture used across the existing `romaincortese-ui` bots, while supporting both long and short opportunities and adapting to live market data, volatility regimes, and news events.

## 1. Executive Decision

Build the new bot as a separate Python repository named `indices-bot` or `indices_bot`, not inside any existing bot repo.

Use the newer `commodities_bot` / `bonds_bot` package shape as the base template because it is compact and deterministic:

- `config.py`
- `models.py`
- `oanda_client.py`
- `risk.py`
- `state.py`
- `runtime.py`
- `telegram.py`
- `strategies/`
- `backtest/`
- tests

Borrow the more mature controls from `gold-bot`:

- adaptive spread tracking
- embedded Telegram command handling in the worker that owns trading state
- macro/news state worker
- missed-opportunity logging
- calibration loading
- drawdown kill switch
- structured runtime status publishing
- backtests that reuse live strategy scorers

Do not start with autonomous code changes or production auto-deploys. The bot should support daily assessment and weekly optimizer workflows through `bot-assessor`, but live trading changes must remain gated.

## 2. Non-Negotiable Requirements

1. The bot must trade indices through OANDA only.
2. The bot must be able to evaluate both LONG and SHORT opportunities for every enabled index.
3. The bot must adapt decisions to real-time market data:
   - current bid/ask and spread
   - short-term momentum
   - ATR volatility regime
   - trend alignment across timeframes
   - session and exchange-open context
4. The bot must adapt decisions to news and macro events:
   - pre-event pause windows
   - post-event settle windows
   - event surprise/direction where available
   - risk-on/risk-off overlays using volatility, rates, USD, and market breadth proxies where available
5. All secrets must come from environment variables.
6. Default execution mode must be safe: paper or signal-only.
7. Runtime logs must be structured enough for `bot-assessor` to parse missed opportunities and blockers.
8. Telegram must alert on startup, order placed/opened, order rejected/not filled, stop/TP closure, manual pause/resume, and runtime errors.
9. The live strategy code and backtest strategy code must be the same code path.
10. The repo must include tests and documentation before production deployment.

## 3. Recommended Repository Structure

```text
indices-bot/
  .github/
    workflows/
      python-tests.yml
  indicesbot/
    __init__.py
    config.py
    models.py
    indicators.py
    oanda_client.py
    marketdata.py
    spread_tracker.py
    news.py
    news_scoring.py
    macro_state.py
    regimes.py
    calibration.py
    risk.py
    exits.py
    state.py
    telegram.py
    runtime.py
    daily_review.py
    strategies/
      __init__.py
      common.py
      opening_range_breakout.py
      trend_pullback.py
      mean_reversion.py
      event_momentum.py
      risk_regime.py
    backtest/
      __init__.py
      data.py
      engine.py
      simulator.py
      reporter.py
      run_backtest.py
  tests/
    test_config.py
    test_oanda_client.py
    test_indicators.py
    test_strategies_long_short.py
    test_news_scoring.py
    test_risk.py
    test_runtime.py
    test_telegram.py
    test_backtest.py
    test_daily_review.py
  main.py
  run_macro_engine.py
  run_daily_calibration.py
  Dockerfile
  Procfile
  railway.toml
  requirements.txt
  pytest.ini
  README.md
  .env.example
```

Entrypoints:

- `main.py`: starts the live/paper/signal runtime worker.
- `run_macro_engine.py`: refreshes news, event, and risk-regime state.
- `run_daily_calibration.py`: runs rolling backtests and publishes calibration/review artifacts.
- `python -m indicesbot.backtest.run_backtest`: explicit historical backtest CLI.

## 4. Instrument Universe

The default universe should focus on liquid index CFDs. Use OANDA instrument discovery at runtime and allow every mapping to be overridden by environment variables because OANDA naming can differ by account/region.

Default canonical symbols:

```python
DEFAULT_UNIVERSE = (
    "SPX500",
    "NAS100",
    "US30",
    "UK100",
    "DE40",
    "EU50",
    "FR40",
    "JP225",
    "HK33",
    "AU200",
)
```

Default OANDA mapping candidates:

```python
OANDA_INSTRUMENTS = {
    "SPX500": "SPX500_USD",
    "NAS100": "NAS100_USD",
    "US30": "US30_USD",
    "UK100": "UK100_GBP",
    "DE40": "DE40_EUR",
    "EU50": "EU50_EUR",
    "FR40": "FR40_EUR",
    "JP225": "JP225_USD",
    "HK33": "HK33_HKD",
    "AU200": "AU200_AUD",
}
```

Implementation rule:

- At boot, call OANDA `/v3/accounts/{account_id}/instruments`.
- Cache `displayPrecision`, `tradeUnitsPrecision`, `marginRate`, and tradeability.
- For each canonical symbol, validate the configured OANDA instrument exists and is currently priceable.
- If a mapping is missing, mark that symbol as unavailable and log `blocked_by=instrument_unavailable` rather than crashing the whole worker.

Universe grouping:

```python
REGION_BUCKETS = {
    "SPX500": "US",
    "NAS100": "US",
    "US30": "US",
    "UK100": "UK",
    "DE40": "EUROPE",
    "EU50": "EUROPE",
    "FR40": "EUROPE",
    "JP225": "ASIA",
    "HK33": "ASIA",
    "AU200": "ASIA_PACIFIC",
}
```

## 5. Configuration Contract

Create `indicesbot/config.py` with typed env parsing helpers and a frozen/slotted `IndicesConfig` dataclass.

Required env vars:

```text
OANDA_ACCOUNT_ID=
OANDA_API_TOKEN=
OANDA_API_KEY=             # optional fallback alias for consistency with FX/Gold
OANDA_ENV=practice         # practice|live
PAPER_TRADE=true
LIVE_TRADING_ENABLED=false
EXECUTION_MODE=paper       # signal_only|paper|live
```

Telegram:

```text
INDICES_TELEGRAM_TOKEN=
INDICES_TELEGRAM_CHAT_ID=
INDICES_TELEGRAM_POLL_SECONDS=5
INDICES_TELEGRAM_HEARTBEAT_MINUTES=60
INDICES_TELEGRAM_OFFSET_FILE=telegram_state.json
```

Redis/state:

```text
REDIS_URL=
INDICES_RUNTIME_STATE_KEY=indices_runtime_state
INDICES_BOT_STATUS_KEY=indices_bot_runtime_status
INDICES_MACRO_STATE_KEY=indices_macro_state
INDICES_CALIBRATION_KEY=indices_calibration
INDICES_DAILY_REVIEW_KEY=bot_assessor:indices:daily_review
INDICES_OVERLAY_KEY=bot_assessor:indices:overlays
INDICES_STATE_FILE=runtime_state.json
INDICES_MACRO_STATE_FILE=indices_macro_state.json
INDICES_CALIBRATION_FILE=calibration.json
INDICES_MISSED_OPPORTUNITIES_FILE=missed_opportunities.json
```

Universe:

```text
INDICES_UNIVERSE=SPX500,NAS100,US30,UK100,DE40,EU50,FR40,JP225,HK33,AU200
OANDA_INSTRUMENT_SPX500=SPX500_USD
OANDA_INSTRUMENT_NAS100=NAS100_USD
OANDA_INSTRUMENT_US30=US30_USD
```

Runtime cadence:

```text
SCAN_INTERVAL_SECONDS=300
INDICES_HEARTBEAT_SECONDS=3600
RUN_ONCE=false
```

Risk:

```text
INDICES_BUDGET_ALLOCATION=1.00
MAX_RISK_PER_TRADE=0.006
MAX_TOTAL_INDICES_RISK=0.025
MAX_OPEN_INDICES_TRADES=3
MAX_OPEN_PER_REGION=2
MAX_OPEN_PER_SYMBOL=1
MAX_LIVE_ORDERS_PER_SCAN=1
MAX_MARGIN_PER_ENTRY_PCT=0.20
MIN_MARGIN_PER_ENTRY_PCT=0.05
DAILY_LOSS_HALT_PCT=0.015
ROLLING_DD_THROTTLE_PCT=0.05
ROLLING_DD_HALT_PCT=0.10
VOL_TARGET_SIZING_ENABLED=true
VOL_TARGET_NAV_BPS=25
```

Spread/execution:

```text
MAX_ENTRY_SPREAD_ATR=0.08
ADAPTIVE_SPREAD_ENABLED=true
ADAPTIVE_SPREAD_WINDOW_MINUTES=30
ADAPTIVE_SPREAD_MULTIPLIER=1.8
ADAPTIVE_SPREAD_MIN_SAMPLES=6
ORDER_TIME_IN_FORCE=FOK
```

News/macro:

```text
NEWS_ENABLED=true
NEWS_PROVIDER=calendar_rss
NEWS_API_KEY=
FRED_API_KEY=
MARKET_DATA_PROVIDER=oanda
MACRO_REFRESH_SECONDS=300
MACRO_STATE_MAX_AGE_MINUTES=30
PRE_EVENT_PAUSE_MINUTES=20
POST_EVENT_SETTLE_MINUTES=15
HIGH_IMPACT_WINDOW_MINUTES=180
EVENT_SURPRISE_ENABLED=true
EVENT_SURPRISE_MIN_ABS_SCORE=0.35
RISK_OFF_FILTER_ENABLED=true
VIX_SPIKE_THRESHOLD_PCT=7.5
YIELD_SPIKE_THRESHOLD_BPS=8
DXY_SPIKE_THRESHOLD_PCT=0.35
```

Backtest/calibration:

```text
BACKTEST_DAYS=30
BACKTEST_GRANULARITY=M15
BACKTEST_OUTPUT_DIR=backtest_output
BACKTEST_CACHE_DIR=backtest_cache
BACKTEST_USE_BID_ASK_DATA=true
BACKTEST_GENERATE_MACRO_STATES=true
BACKTEST_WALK_FORWARD_TRAIN_DAYS=60
BACKTEST_WALK_FORWARD_TEST_DAYS=20
BACKTEST_MONTE_CARLO_ITERATIONS=1000
```

## 6. Core Data Models

Create `indicesbot/models.py` with these core dataclasses.

```python
@dataclass(frozen=True, slots=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    complete: bool = True


@dataclass(frozen=True, slots=True)
class IndexQuote:
    symbol: str
    instrument: str
    bid: float
    ask: float
    mid: float
    spread: float
    tradeable: bool
    status: str
    time: datetime


@dataclass(frozen=True, slots=True)
class NewsEvent:
    id: str
    title: str
    region: str
    impact: str
    occurs_at: datetime
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    source: str = ""


@dataclass(frozen=True, slots=True)
class EventScore:
    event_id: str
    region: str
    direction: str      # RISK_ON, RISK_OFF, NEUTRAL
    score: float        # -1..1, negative is bearish/risk-off for indices
    confidence: float   # 0..1
    reason: str


@dataclass(frozen=True, slots=True)
class MarketRegime:
    symbol: str
    region: str
    trend: str          # BULL, BEAR, RANGE
    volatility: str     # LOW, NORMAL, HIGH, EXTREME
    risk_mode: str      # RISK_ON, RISK_OFF, MIXED
    session: str
    score_offset_long: float = 0.0
    score_offset_short: float = 0.0
    risk_multiplier: float = 1.0
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Opportunity:
    symbol: str
    instrument: str
    direction: str      # LONG or SHORT
    strategy: str
    score: float
    entry_price: float
    stop_price: float
    take_profit_price: float | None
    atr: float
    risk_reward: float
    risk_multiplier: float
    rationale: str
    metadata: dict[str, object]


@dataclass(slots=True)
class IndexPosition:
    symbol: str
    instrument: str
    direction: str
    strategy: str
    units: float
    order_units: float
    entry_price: float
    stop_price: float
    take_profit_price: float | None
    opened_at: datetime
    region: str
    order_id: str
    metadata: dict[str, object]
```

Implementation rule: strategy functions must return `Opportunity | None` and also accept a mutable `reasons` list. Every rejection should append a structured reason such as `TREND_PULLBACK:ema_not_aligned`.

## 7. OANDA Integration

Implement `indicesbot/oanda_client.py` based on the cleaner commodities/bonds clients plus the retry and URL sanitization behavior from Gold.

Required methods:

```python
class OandaClient:
    def tradeable_instruments(self) -> list[str]: ...
    def instrument_details(self, instrument: str) -> InstrumentDetails: ...
    def instrument_tradeable(self, instrument: str) -> tuple[bool, str]: ...
    def account_summary(self) -> AccountSummary: ...
    def account_nav(self) -> float: ...
    def account_margin_available(self) -> float: ...
    def account_currency(self) -> str: ...
    def open_positions(self) -> set[str]: ...
    def open_trades(self) -> list[dict[str, object]]: ...
    def current_quote(self, symbol: str, instrument: str) -> IndexQuote: ...
    def candles(self, instrument: str, count: int, granularity: str, *, price: str = "M") -> list[Candle]: ...
    def candles_range(self, instrument: str, granularity: str, start: datetime, end: datetime, *, price: str = "M") -> list[Candle]: ...
    def home_conversion_factor(self, instrument: str, side: str) -> float: ...
    def place_market_order(self, opportunity: Opportunity, units: float) -> dict[str, object]: ...
    def close_trade(self, trade_id: str, units: str = "ALL") -> dict[str, object]: ...
```

Execution rules:

- Use `POST /v3/accounts/{account_id}/orders`.
- Use signed units: positive for LONG, negative for SHORT.
- Use `MARKET`, `FOK`, and `positionFill=DEFAULT` by default.
- Attach `stopLossOnFill` on every live order.
- Attach `takeProfitOnFill` only when the strategy has a fixed target. Trend strategies may manage exits dynamically.
- Add `clientExtensions.tag="indicesbot"` and `clientExtensions.comment` with symbol, direction, strategy, and score.
- If OANDA returns `orderRejectTransaction` or `orderCancelTransaction`, raise/return a structured no-fill result and send Telegram.
- Do not silently record a position unless `orderFillTransaction.tradeOpened.tradeID` or an equivalent fill id exists.

Market-data rules:

- Use M5/M15 for entry timing.
- Use H1/H4/D for regime and support/resistance.
- Request bid/ask candles for backtests when possible.
- Filter incomplete candles except when explicitly configured for live incomplete-candle analysis.
- Cache historical backtest candles under `backtest_cache/`.

## 8. Runtime Flow

Implement `indicesbot/runtime.py` as the single owner of broker-affecting actions.

High-level loop:

```text
boot
  load config
  build OANDA client
  build state store
  build Telegram client
  publish boot status
  send Telegram startup alert

every scan interval
  service Telegram commands
  process queued controls: pause, resume, sync, closeall
  sync OANDA open positions with local state
  manage open positions: break-even, trailing stop, stale timeout, closure detection
  evaluate drawdown kill switch
  skip if paused, halted, weekend/holiday/off-session
  fetch account summary and margin
  load macro/news/regime state
  load calibration and bot-assessor overlays
  for each enabled index:
    validate instrument is tradeable
    fetch quote and update adaptive spread tracker
    fetch M5/M15/H1/H4/D candles
    classify market regime
    run all strategies for LONG and SHORT
    record rejected opportunity reasons
  select best opportunity under score/risk/correlation gates
  resize using volatility, stop distance, margin, and region caps
  place one order max per scan by default
  record order/fill/reject in state
  send Telegram alert
  publish runtime status
```

Log all scan decisions with structured fields:

```text
INFO opportunity symbol=SPX500 direction=LONG strategy=OPENING_RANGE_BREAKOUT score=82.5 atr=18.2 region=US
INFO skipped symbol=NAS100 direction=SHORT blocked_by=spread_too_wide strategy=EVENT_MOMENTUM spread=3.8 adaptive_cap=2.4
INFO trade_opened symbol=SPX500 direction=LONG strategy=TREND_PULLBACK units=2 order_id=12345 entry=5240.1 sl=5205.0
INFO trade_closed symbol=SPX500 direction=LONG order_id=12345 pnl=112.5 reason=take_profit
```

State file/Redis shape:

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-05-07T12:00:00Z",
  "paused": false,
  "halted": false,
  "execution_mode": "paper",
  "account_nav": 10000.0,
  "account_margin_available": 8900.0,
  "open_positions": [],
  "last_scan": {
    "status": "idle",
    "session": "US_CASH_OPEN",
    "best_opportunity": null,
    "blocked_by": "score_below_threshold"
  },
  "recent_events": [],
  "missed_opportunities": []
}
```

## 9. Sessions And Trading Windows

Use exchange-aware sessions with Python `zoneinfo`, not fixed UTC-only guesses.

Session definitions:

- US indices: New York timezone. Focus on cash open, morning trend, afternoon continuation, and last-hour risk.
- UK100: London timezone.
- DE40/EU50/FR40: Europe/Berlin or Europe/Paris timezone.
- JP225: Asia/Tokyo timezone.
- HK33: Asia/Hong_Kong timezone.
- AU200: Australia/Sydney timezone.

Default behavior:

- Avoid new entries during the final 10 minutes of local cash session.
- Avoid new entries during known market closures or OANDA non-tradeable status.
- Prefer opening-range strategies in the first 30 to 120 minutes of the local cash session.
- Prefer trend-pullback strategies outside the initial opening volatility window.
- Allow event-momentum after major events once spreads settle.

## 10. News And Macro Engine

Create `run_macro_engine.py` and `indicesbot/news.py` / `indicesbot/macro_state.py`.

News scope for indices:

- US: CPI, PPI, NFP, unemployment, FOMC, Fed speakers, GDP, retail sales, ISM/PMI, consumer confidence, jobless claims.
- Europe: ECB, Eurozone CPI/GDP/PMI, German ZEW/IFO/CPI, French CPI/PMI.
- UK: BoE, CPI, GDP, jobs, retail sales, PMI.
- Japan: BoJ, CPI, GDP, Tankan, yen intervention headlines.
- China/HK/Australia: China PMI, CPI, trade, PBoC policy, RBA, Australian jobs/CPI.
- Global risk: VIX spikes, US yields, DXY, oil shock, major geopolitical risk headline markers.

Macro state payload:

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-07T12:00:00Z",
  "source_status": {
    "calendar": "ok",
    "fred": "ok",
    "market_proxy": "cached"
  },
  "events": [
    {
      "id": "us-cpi-2026-05",
      "title": "US CPI",
      "region": "US",
      "impact": "HIGH",
      "occurs_at": "2026-05-13T12:30:00Z",
      "actual": null,
      "forecast": 3.4,
      "previous": 3.5
    }
  ],
  "event_scores": [],
  "risk_regime": {
    "global": "MIXED",
    "vix_change_pct": 2.1,
    "us10y_change_bps": 3.5,
    "dxy_change_pct": 0.1
  },
  "region_bias": {
    "US": {"direction": "NEUTRAL", "score": 0.0, "confidence": 0.4},
    "EUROPE": {"direction": "RISK_ON", "score": 0.25, "confidence": 0.5}
  }
}
```

News behavior:

- If a high-impact event for a symbol's region is within `PRE_EVENT_PAUSE_MINUTES`, block new entries unless a strategy explicitly supports pre-event positioning. Default: block.
- During the first `POST_EVENT_SETTLE_MINUTES`, block new entries until spread stabilizes.
- After settle, allow `EVENT_MOMENTUM` when event surprise and price impulse agree.
- If macro state is stale, block event-driven strategies and reduce risk for all strategies.
- Always cache the last valid macro state locally and in Redis.

## 11. Strategy Set

All strategies must evaluate both LONG and SHORT. Strategy code must be pure, deterministic, and directly reused by backtests.

### 11.1 Opening Range Breakout

Module: `indicesbot/strategies/opening_range_breakout.py`

Purpose: trade first-session directional expansion after local cash open.

Inputs:

- M5/M15 candles
- local exchange session clock
- H1/H4 trend hint
- quote spread/adaptive cap
- macro risk regime

LONG setup:

- first N minutes range has formed
- close breaks above opening range high by `buffer_atr`
- impulse candle body is at least `min_body_atr`
- H1/H4 trend is bullish or neutral
- risk regime is not strongly risk-off
- spread is stable

SHORT setup:

- close breaks below opening range low by `buffer_atr`
- impulse candle body is at least `min_body_atr`
- H1/H4 trend is bearish or neutral
- risk regime is not strongly risk-on
- spread is stable

Reject reasons:

- `range_not_ready`
- `breakout_not_confirmed`
- `impulse_missing`
- `against_macro_regime`
- `spread_too_wide`

### 11.2 Trend Pullback

Module: `indicesbot/strategies/trend_pullback.py`

Purpose: enter aligned pullbacks in established index trends.

LONG setup:

- H4 fast EMA above slow EMA
- H1 close above medium EMA
- M15 pulls back toward fast/medium EMA
- bullish reversal candle, EMA reclaim, or momentum recapture
- stop below pullback swing or ATR stop

SHORT setup:

- H4 fast EMA below slow EMA
- H1 close below medium EMA
- M15 pulls back upward toward fast/medium EMA
- bearish reversal candle, EMA rejection, or momentum rollover
- stop above pullback swing or ATR stop

Regime behavior:

- In high volatility, widen stop and reduce risk multiplier.
- In extreme volatility, block unless event momentum explicitly confirms.

### 11.3 Mean Reversion

Module: `indicesbot/strategies/mean_reversion.py`

Purpose: fade overextensions near support/resistance when trend strength is weak and no major event is imminent.

LONG setup:

- price below lower Bollinger/Keltner band
- RSI oversold or bullish divergence
- near prior day/week support or VWAP deviation band
- volatility not extreme
- no high-impact event within pause window

SHORT setup:

- price above upper Bollinger/Keltner band
- RSI overbought or bearish divergence
- near prior day/week resistance or VWAP deviation band
- volatility not extreme
- no high-impact event within pause window

Mean reversion must be disabled during strong opening range expansion or fresh event momentum.

### 11.4 Event Momentum

Module: `indicesbot/strategies/event_momentum.py`

Purpose: trade post-news continuation after surprise and price confirm.

LONG setup:

- post-event settle elapsed
- event score is risk-on for the index region
- price impulse is upward and above event range high
- spread stabilized across several checks
- VIX/yields/DXY do not contradict the move strongly

SHORT setup:

- post-event settle elapsed
- event score is risk-off for the index region
- price impulse is downward and below event range low
- spread stabilized across several checks
- VIX/yields/DXY confirm or do not contradict strongly

### 11.5 Risk-Regime Overlay

Module: `indicesbot/strategies/risk_regime.py`

Purpose: not a standalone strategy initially. It adjusts score/risk/blockers for all opportunities.

Examples:

- VIX spike plus rising yields: add score to SHORT US indices and reduce/block LONG.
- VIX falling plus breadth improving: add score to LONG indices and reduce/block SHORT.
- DXY/yields spike after hot inflation: bias NAS100 shorts more than US30 shorts.
- Major central bank event for region: reduce risk or block non-event strategies.

## 12. Opportunity Selection

Implement `select_best_opportunity(opportunities, config, state, account, calibration)`.

Rules:

- Minimum score default: 70.
- Only one live order per scan by default.
- Do not open if symbol already has an open position.
- Do not open if region cap would be exceeded.
- Do not open if total risk cap would be exceeded.
- Prefer the highest score after calibration and macro overlays.
- Tie-breakers:
  1. stronger risk/reward
  2. lower spread-to-ATR
  3. better historical calibration bucket
  4. lower region correlation exposure

Record the best rejected opportunity as a missed opportunity when score was above threshold but blocked by risk, spread, event, tradeability, margin, or open-position constraints.

## 13. Risk And Sizing

Implement `indicesbot/risk.py`.

Sizing inputs:

- account NAV or paper balance
- account currency
- margin available
- instrument margin rate
- home conversion factor
- entry price
- stop distance
- ATR
- opportunity score
- strategy risk multiplier
- event risk multiplier
- calibration multiplier

Required functions:

```python
def position_from_opportunity(opportunity, config, account, instrument_details, conversion_factor) -> IndexPosition: ...
def can_open(position, state, config) -> tuple[bool, str]: ...
def total_open_risk(state) -> float: ...
def region_open_risk(state, region) -> float: ...
def resize_for_margin_budget(position, account, config) -> tuple[IndexPosition | None, str | None]: ...
```

Risk rules:

- Base risk per trade: `MAX_RISK_PER_TRADE`, default 0.6 percent of NAV.
- Volatility target sizing: reduce size when ATR regime is high.
- Margin cap: no entry may consume more than `MAX_MARGIN_PER_ENTRY_PCT` of available margin.
- Total open risk cap: default 2.5 percent NAV.
- Region cap: default 1.5 percent NAV per region.
- Symbol cap: one open position per symbol.
- Hard drawdown halt: no new entries after configured rolling drawdown threshold.
- Soft drawdown throttle: reduce per-trade risk after configured drawdown threshold.

Do not use full-balance allocation for indices. Indices are correlated and gap-prone. Use risk-at-stop and margin caps.

## 14. Exits And Trade Management

Implement `indicesbot/exits.py` and runtime management.

Every entry must have a stop loss.

Exit plan by strategy:

- Opening Range Breakout: partial at 1.2R, move stop to break-even, trail by ATR or session VWAP after 1.5R.
- Trend Pullback: partial at 1.5R, trail using H1 EMA or ATR multiple.
- Mean Reversion: fixed target near VWAP/mid-band, quicker timeout if no mean reversion occurs.
- Event Momentum: wider initial stop, partial at 1.0R to 1.25R, trail if impulse continues.

Runtime should detect closures by syncing OANDA open positions/trades and comparing against state. Telegram closure alerts must include realized/unrealized PnL if available, held time, strategy, and reason.

## 15. Telegram Contract

Use an embedded Telegram client like Gold and the simpler send/getUpdates behavior from commodities/bonds.

Commands:

- `/help`
- `/status`
- `/last`
- `/open`
- `/risk`
- `/events`
- `/pause`
- `/resume`
- `/sync`
- `/closeall`

Important rule: Telegram commands that affect broker state must be queued into runtime state and executed by `runtime.py` on the next cycle. Telegram must not directly call OANDA order endpoints.

Alerts:

- startup/boot manifest
- heartbeat
- new high-quality signal in signal-only mode
- order submitted
- order filled/opened
- order rejected/not filled
- spread-blocked opportunity
- missed opportunity above threshold
- partial profit
- stop moved to break-even
- trailing stop update
- trade closed
- pause/resume/halt
- runtime error

Message content should include symbol, direction, strategy, score, entry, stop, target, units, risk estimate, reason, and mode.

## 16. Daily Review And Bot-Assessor Integration

The new bot should be easy to add to `bot-assessor`.

Add `indicesbot/daily_review.py` that writes:

```json
{
  "schema_version": "1.0",
  "bot_id": "indices",
  "generated_at": "2026-05-07T06:00:00Z",
  "summary": {
    "signals": 12,
    "orders_opened": 1,
    "orders_closed": 1,
    "missed_opportunities": 4,
    "blocked_by": {"spread_too_wide": 2, "event_pause": 1, "risk_cap": 1}
  },
  "incidents": [],
  "missed_opportunities": [],
  "recommendations": [],
  "backtest": {},
  "risk_flags": []
}
```

Redis keys:

- Runtime status: `indices_bot_runtime_status`
- Macro state: `indices_macro_state`
- Calibration: `indices_calibration`
- Daily review: `bot_assessor:indices:daily_review`
- Optional overlays: `bot_assessor:indices:overlays`

Allowed overlay types:

- `score_offset`
- `strategy_block`
- `symbol_block`
- `region_block`
- `risk_multiplier`

Overlay safety:

- Overlays must expire.
- Overlays must never change broker credentials, execution mode, max leverage, or order path.
- Overlay risk multipliers must be clamped between 0.25 and 1.15.
- Symbol/strategy/region blocks are safe.
- Code changes remain PR-only through phase 4/5 of `bot-assessor`.

## 17. Backtesting And Calibration

Backtest must reuse live strategy functions.

Data provider:

- OANDA historical candles with local cache.
- Bid/ask candle mode when available.
- Fallback to mid candles with spread model if bid/ask unavailable.
- Event replay from historical event JSON/CSV.
- Optional market proxy history: VIX, DXY, US 10Y yield, US 2Y yield, region ETF proxies.

Simulator must include:

- bid/ask spread
- slippage
- FOK/no-fill approximation on wide spread
- stop loss
- take profit
- partial profit
- break-even move
- trailing stop
- timeout exits
- session close exit rules where configured
- margin and risk caps

Backtest outputs:

```text
backtest_output/<window>/summary.json
backtest_output/<window>/trade_journal.csv
backtest_output/<window>/equity_curve.csv
backtest_output/<window>/calibration.json
backtest_output/<window>/daily_review.json
```

`summary.json` required metrics:

- total trades
- total PnL
- return percent
- profit factor
- win rate
- max drawdown
- average R
- expectancy
- trades by strategy
- trades by symbol
- trades by direction
- trades by session
- blocked opportunity counts

Calibration should produce grouped stats:

- strategy
- strategy + symbol
- strategy + direction
- strategy + symbol + direction
- strategy + session
- strategy + regime

Live runtime uses calibration only when valid:

- fresh enough
- enough trades
- schema version supported
- not marked failed

## 18. Railway Deployment

Recommended Railway services:

1. `worker`: `python main.py`
2. `macro`: `python run_macro_engine.py`
3. `calibration`: `python run_daily_calibration.py`, scheduled daily

Use one repo and one image.

`Dockerfile`:

- Python 3.12 slim
- install requirements
- run as non-root if convenient
- default command `python main.py`

`railway.toml` can define default worker command, but scheduled services may use Railway UI start commands.

Recommended initial deployment:

- `EXECUTION_MODE=signal_only`
- `PAPER_TRADE=true`
- `LIVE_TRADING_ENABLED=false`
- Telegram enabled
- Redis enabled
- OANDA practice credentials only

Only move to live after paper mode has:

- correct instrument discovery
- correct bid/ask/spread values
- correct unit precision
- correct stop-loss placement
- correct Telegram open/close alerts
- at least 30 days of assessment/backtest stability

## 19. Tests Required Before First PR Completion

Minimum test suite:

1. Config parsing:
   - defaults
   - OANDA aliases
   - universe overrides
   - invalid bool raises
2. OANDA client:
   - instrument details cache
   - pricing tradeability
   - bid/ask parsing
   - order rejection extraction
   - signed units and precision formatting
3. Strategy tests:
   - each strategy can generate LONG and SHORT
   - rejects append structured reasons
   - event pause blocks non-event strategies
   - risk-off overlay boosts shorts and suppresses longs
4. Risk tests:
   - position sizing by stop distance
   - margin cap resizing
   - region cap
   - total risk cap
   - drawdown halt
5. Runtime tests:
   - no OANDA credentials in signal-only mode
   - paper order recorded
   - live order reject does not create state position
   - Telegram order placed/opened/closed messages
   - missed-opportunity record when high score is blocked
6. Backtest tests:
   - simulator fills long and short correctly
   - stop and target logic
   - partial and trailing logic
   - summary and calibration artifacts written
7. Daily review tests:
   - schema fields exist
   - blocker counts aggregate
   - Redis payload is JSON-safe

CI:

```yaml
name: Python Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q
```

## 20. Implementation Phases For The AI Developer

### Phase A: Scaffold

Deliverables:

- repo structure
- package imports
- config
- models
- OANDA client skeleton and tests
- README and `.env.example`
- CI

Acceptance:

- `pytest -q` passes
- `python main.py` starts in signal-only mode without credentials and exits cleanly when `RUN_ONCE=true`

### Phase B: Market Data, Indicators, Strategies

Deliverables:

- OANDA candles/quotes
- indicators
- regime classification
- four strategy modules
- long/short unit tests

Acceptance:

- every enabled strategy has at least one deterministic LONG and SHORT fixture test
- rejected setups include structured blocker reasons

### Phase C: Runtime, State, Telegram

Deliverables:

- runtime scan loop
- state store local and Redis
- Telegram commands and alerts
- paper execution path
- missed-opportunity logging

Acceptance:

- paper mode can open/manage/close a simulated position
- Telegram tests cover startup, open, reject, close, pause, resume

### Phase D: News/Macro Engine

Deliverables:

- news/event fetcher
- cached fallback
- event scoring
- risk-regime state
- pre/post event gates

Acceptance:

- high-impact event blocks non-event entries before release
- post-event momentum requires direction and impulse confirmation
- stale macro state reduces risk or blocks event strategies

### Phase E: Backtest And Calibration

Deliverables:

- OANDA historical cache
- simulator
- backtest CLI
- summary/report artifacts
- calibration JSON
- daily review JSON

Acceptance:

- `python -m indicesbot.backtest.run_backtest --days 30` writes summary, trade journal, equity curve, calibration
- live strategy functions are reused directly

### Phase F: Railway And Bot-Assessor Readiness

Deliverables:

- Dockerfile
- railway.toml
- run scripts
- runtime status keys
- daily review keys
- log formats

Acceptance:

- ready to add to `bot-assessor` config with `python -m indicesbot.backtest.run_backtest`
- all secrets are environment variables
- no hard-coded Telegram/OANDA/Redis values

## 21. Initial `bot-assessor` Config Entry

After the repo exists, add a bot-assessor entry like this:

```json
{
  "id": "indices",
  "name": "Indices Bot",
  "github_repo": "romaincortese-ui/indices-bot",
  "railway_service": "indices-bot",
  "railway_environment": "production",
  "setup_command": ["python", "-m", "pip", "install", "-r", "requirements.txt"],
  "backtest_command": ["python", "-m", "indicesbot.backtest.run_backtest"],
  "backtest_env": {"BACKTEST_DAYS": "30"},
  "test_command": ["python", "-m", "pytest"],
  "maturity": "new_high_risk",
  "compatible_review_redis_key": "bot_assessor:indices:daily_review",
  "overlay_redis_key": "bot_assessor:indices:overlays",
  "allow_parameter_overlays": false,
  "allowed_overlay_types": ["score_offset", "strategy_block", "symbol_block", "region_block", "risk_multiplier"],
  "optimizer_enabled": false,
  "optimizer_command": [],
  "auto_merge_enabled": false
}
```

Keep overlays and optimizer disabled until the bot has enough real paper/live observation data.

## 22. Important Design Choices And Rationale

1. Use the commodities/bonds package shape, not the FX monolith. It is easier for an AI developer to implement and test quickly.
2. Bring in Gold's mature controls because indices are gap-prone and news-sensitive.
3. Prefer risk-at-stop sizing over full-balance allocation. Indices are highly correlated and can gap on macro shocks.
4. Use both LONG and SHORT paths from day one. Do not implement a long-only first version.
5. Treat news as a gate and modifier first, then as a strategy only after post-event settle.
6. Make OANDA instrument mapping discoverable and overrideable. This avoids account/region-specific symbol-name failures.
7. Keep Telegram commands broker-safe by routing all actions through runtime state.
8. Make backtesting use the live strategy code. No duplicated strategy implementation.
9. Publish structured daily review data so `bot-assessor` can monitor the bot from the start.
10. Delay optimizer and auto-merge until the bot has stable paper-mode evidence.

## 23. Final Acceptance Criteria For The First Production-Ready PR

The AI developer should consider the first production-ready implementation complete only when all items pass:

- `pytest -q` passes locally and in GitHub Actions.
- `python main.py` runs in signal-only mode with no OANDA credentials.
- OANDA practice mode discovers at least the configured instruments available to the account.
- Paper mode can produce both LONG and SHORT simulated orders from fixtures.
- Live mode refuses to start unless `LIVE_TRADING_ENABLED=true`, `PAPER_TRADE=false`, OANDA credentials exist, and Telegram is configured.
- Every live order includes stop loss on fill.
- Order rejection/no-fill does not create a local open position.
- Runtime sends Telegram alerts for open and close events.
- `python -m indicesbot.backtest.run_backtest --days 30` writes expected artifacts.
- `run_daily_calibration.py` writes `calibration.json` and `daily_review.json`.
- Structured logs include `symbol=`, `direction=`, `strategy=`, and `blocked_by=` where applicable.
- README explains local setup, Railway setup, environment variables, OANDA instrument mapping, and safe rollout.

## 24. Suggested Initial Development Prompt

Use this prompt for the AI agent developer:

```text
Build a new standalone Python repo for an OANDA indices trading bot using the specification in docs/indices-bot-solution-design.md. Follow the existing romaincortese-ui bot conventions: small deterministic modules, no hard-coded secrets, Telegram alerts from the runtime owner, OANDA practice/paper defaults, Redis-compatible runtime state, backtests that reuse live strategy code, and tests for every pure module. Implement phases A through F in order. Do not enable live trading by default. Do not add autonomous code optimization or auto-merge for this new bot. The bot must evaluate both LONG and SHORT opportunities for every enabled index and must adapt entries, exits, and risk to live spread, volatility regime, session, and news/event state.
```