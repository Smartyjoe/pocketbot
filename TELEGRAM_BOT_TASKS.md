# Telegram Trading Bot — Build Task List

**Status:** All tasks are `pending` until explicitly started.

---

## Phase 0: Project Foundation

These tasks set up the scaffold. No broker or Telegram code yet.

### 0.1 Initialize project structure

- [ ] Create `pyproject.toml` with `uv` workspace, project metadata, and dependency groups (`default`, `dev`, `ml`, `backtest`)
- [ ] Run `uv sync` to lock all dependencies and verify the lockfile
- [ ] Create root `__init__.py` files for all packages (`domain/`, `application/`, `infrastructure/`, `interfaces/`, `engine/`, `config/`)
- [ ] Create `config/settings.py` with all pydantic-settings models (AppSettings → PostgresConfig, RedisConfig, BrokerConfig, TelegramConfig, TradingConfig, LoggingConfig)
- [ ] Create `config/logging.py` with structlog configuration for development (colored console) and production (JSON)

### 0.2 Set up tooling configuration

- [ ] Create `pyproject.toml` sections for:
  - `[tool.ruff]` — line length=120, select=I (isort), E, W, F, N, D (pydocstyle), UP (pyupgrade), ANN (annotations)
  - `[tool.mypy]` — strict, disallow_untyped_defs=True, warn_unused_ignores=True
  - `[tool.pytest.ini_options]` — asyncio_mode=auto, testpaths=tests, markers=unit,integration,e2e
- [ ] Create `tests/conftest.py` with shared fixtures placeholder
- [ ] Create `.gitignore` (include `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `mlruns/`, `storage/`)

### 0.3 Create Docker Compose for local development

- [ ] Create `docker-compose.yml` with services:
  - `postgres` — PostgreSQL 16, port 5432, volume for data persistence
  - `redis` — Redis 7 Alpine, port 6379
  - `app` — build from Dockerfile, mount source for hot-reload
- [ ] Create `Dockerfile` (multi-stage: builder with uv, runtime with python:3.12-slim)
- [ ] Create `docker-compose.override.yml` for development (extra env vars, port mappings)

---

## Phase 1: Domain Layer

Pure Python. Zero infrastructure imports. Fully testable without any external services.

### 1.1 Value Objects

- [ ] Implement `domain/value_objects/symbol.py`:
  - `Symbol(code: str, broker_name: str)` — frozen Pydantic model, validates non-empty code, string normalization
- [ ] Implement `domain/value_objects/money.py`:
  - `Money(amount: Decimal, currency: str)` — frozen, arithmetic operators (add, sub, mul, neg), comparison operators, rounds to 2 decimals
- [ ] Implement `domain/value_objects/timeframe.py`:
  - `Timeframe(seconds: int)` — frozen, validates seconds > 0, known constants (TF_60=60, TF_300=300), `to_timedelta()` helper
- [ ] Implement `domain/value_objects/direction.py`:
  - `Direction(enum.Enum)` — `CALL`, `PUT`, `INVALID`. Method `from_str(s: str) -> Direction`. Property `opposite -> Direction`
- [ ] Implement `domain/value_objects/confidence.py`:
  - `Confidence(score: float)` — frozen, validates 0.0 <= score <= 1.0, comparison operators, label property (HIGH >= 0.8, MEDIUM >= 0.6, LOW < 0.6)

### 1.2 Domain Events

- [ ] Implement `domain/events/base.py`:
  - `DomainEvent` base — frozen Pydantic model, auto-generated `event_id: UUID`, `occurred_at: datetime`
- [ ] Implement `domain/events/signal_generated.py`:
  - `SignalGenerated(signal_id, strategy_id, symbol, direction, confidence, feature_values, candle_timestamp, model_version)` extends DomainEvent
- [ ] Implement `domain/events/trade_opened.py`:
  - `TradeOpened(trade_id, signal_id, strategy_id, symbol, direction, amount, entry_price, expires_at, broker_trade_id)` extends DomainEvent
- [ ] Implement `domain/events/trade_expired.py`:
  - `TradeExpired(trade_id, symbol, direction, entry_price, exit_price, result, profit_loss)` extends DomainEvent
- [ ] Implement `domain/events/balance_changed.py`:
  - `BalanceChanged(old_balance, new_balance, currency)` extends DomainEvent
- [ ] Implement `domain/events/broker_status.py`:
  - `BrokerConnected`, `BrokerDisconnected(reconnect_attempt, next_attempt_in)`, `BrokerError(error_code, message)` extend DomainEvent

### 1.3 Entities

- [ ] Implement `domain/entities/signal.py`:
  - `Signal(symbol, direction, confidence, strategy_id, features: dict[str, float], model_version, candle_timestamp, generated_at, metadata: dict[str, Any])` — Pydantic model, auto-id, auto-generated_at
- [ ] Implement `domain/entities/trade.py`:
  - `Trade(symbol, direction, amount: Money, timeframe: Timeframe, status: TradeStatus(PENDING|OPEN|EXPIRED|SETTLED), entry_price: Decimal, exit_price: Decimal|None, result: TradeResult(WIN|LOSS|DRAW)|None, payout: int, profit_loss: Money|None, broker_trade_id: str|None, signal_id: UUID|None, strategy_id: UUID|None, opened_at, expires_at, settled_at|None, metadata: dict)` — Pydantic model, auto-id
  - `TradeStatus` and `TradeResult` enums in the same file
- [ ] Implement `domain/entities/strategy.py`:
  - `Strategy(name, version, status: StrategyStatus(DRAFT|ACTIVE|PAUSED|ARCHIVED), symbols: list[Symbol], timeframe: Timeframe, max_position_size: Money|None, max_daily_trades: int|None, cooldown_minutes: int, risk_per_trade: Decimal, model_uri: str|None, feature_config: FeatureConfig|None, metadata: dict)` — Pydantic model, auto-id
  - `StrategyStatus` enum

### 1.4 Repository Ports (Protocols)

- [ ] Implement `domain/ports/repositories.py`:
  - `SignalRepository(Protocol)` — `save(signal)`, `get(id)`, `get_by_strategy(strategy_id, limit)`, `get_by_symbol(symbol, since, limit)`, `get_latest(symbol)`
  - `TradeRepository(Protocol)` — `save(trade)`, `get(id)`, `get_by_strategy(strategy_id, limit)`, `get_by_symbol(symbol, since)`, `get_pending()`, `get_open()`, `update_result(id, result, pnl, exit_price)`
  - `StrategyRepository(Protocol)` — `save(strategy)`, `get(id)`, `get_active()`, `get_by_name(name)`, `delete(id)`
  - `EventStore(Protocol)` — `append(event)`, `get_by_aggregate(aggregate_id, aggregate_type)`, `get_by_type(event_type, since)`
- [ ] Implement `domain/ports/broker.py`:
  - `BrokerPort(Protocol)` — `connect()`, `disconnect()`, `is_connected()`, `get_balance() -> Money`, `get_assets()`, `get_payout(symbol)`, `place_option(symbol, amount, direction, timeframe)`, `get_trade_result(broker_trade_id)`, `subscribe_candles(symbol, timeframe) -> AsyncIterator[Candle]`, `get_candles(symbol, timeframe, count)`, property `on_disconnect -> AsyncIterator[DisconnectEvent]`
- [ ] Implement `domain/ports/event_bus.py`:
  - `EventBus(Protocol)` — `publish(event)`, `subscribe(event_type, handler)`, `unsubscribe(event_type, handler)`
- [ ] Implement `domain/ports/clock.py`:
  - `Clock(Protocol)` — `now() -> datetime`, `utcnow() -> datetime`, `sleep(seconds)`, property `on_tick(interval) -> AsyncIterator[datetime]`

### 1.5 Domain Services

- [ ] Implement `domain/services/signal_evaluator.py`:
  - `SignalEvaluator` — stateless domain service. `evaluate(features: dict, confidence: Confidence, threshold: float) -> Direction`. Pure logic for translating model output to CALL/PUT.
- [ ] Implement `domain/services/risk_calculator.py`:
  - `RiskCalculator` — `calculate_position_size(balance: Money, risk_per_trade: Decimal, max_position: Money|None) -> Money`. `should_allow_trade(strategy, daily_trade_count, last_trade_time, current_drawdown) -> bool`.

### 1.6 Domain Tests

- [ ] Write tests for all value objects (validation, immutability, arithmetic)
- [ ] Write tests for all entities (creation, state transitions, invariants)
- [ ] Write tests for domain events (serialization, field types, frozen)
- [ ] Write tests for domain services (signal evaluation edge cases, position sizing)

---

## Phase 2: Infrastructure Layer

Adapts external systems to domain ports. Depends on domain protocols only.

### 2.1 Event Bus

- [ ] Implement `infrastructure/event_bus.py`:
  - `InMemoryEventBus` implements `EventBus` — type-routed, async handlers, thread-safe, bounded handler execution via TaskGroup
- [ ] Write integration test with multiple subscribers, error handling, and cancellation

### 2.2 Clock

- [ ] Implement `infrastructure/clock.py`:
  - `SystemClock` implements `Clock` — returns real time, uses `asyncio.sleep`. `on_tick(interval)` yields current time every interval via async generator

### 2.3 Broker Adapter (BinaryOptionsTools-v2)

- [ ] Implement `infrastructure/broker/broker_adapter.py`:
  - `PocketOptionBrokerAdapter` implements `BrokerPort`
  - Constructor: takes SSID, config. Wraps `PocketOptionAsync` from `binaryoptionstools`
  - `connect()`: creates `PocketOptionAsync`, enters async context, waits for assets
  - `disconnect()`: calls `shutdown()` on client
  - `is_connected()`: checks internal connection state
  - `get_balance()`: calls `client.balance()`, returns `Money`
  - `get_assets()`: calls `client.active_assets()`, returns list of asset info
  - `get_payout(symbol)`: calls `client.payout(symbol)`
  - `place_option(...)`: calls `client.buy(symbol, amount, timeframe, direction)` or `client.sell(...)`, maps response to `Trade`
  - `get_trade_result(broker_trade_id)`: calls `client.check_win(broker_trade_id)`, maps to `TradeResult`
  - `subscribe_candles(symbol, timeframe)`: calls `client.subscribe_symbol(symbol)`, yields parsed `Candle` objects
  - `get_candles(symbol, timeframe, count)`: calls `client.candles(symbol, timeframe)`, returns list
  - `on_disconnect`: property returning async generator that yields `DisconnectEvent` on connection loss
  - Internal reconnection: delegates to BinaryOptionsTools-v2's built-in reconnect, monitors via client events
- [ ] Implement `infrastructure/broker/virtual_market.py`:
  - `ConfigurableVirtualMarket` — extends BinaryOptionsTools-v2's VirtualMarket with configurable spread (pips), slippage (%), and latency simulation (ms delay on buy/sell)
- [ ] Implement `infrastructure/broker/backtest_broker.py`:
  - `BacktestBroker` implements `BrokerPort` — deterministic, uses pre-loaded candle data, resolves trades at expiry by checking candle close price
- [ ] Implement `infrastructure/broker/exceptions.py`:
  - Map BinaryOptionsTools-v2 exceptions to domain `BrokerError` subtypes
- [ ] Write integration test with `PocketOptionAsync` using real SSID (requires `POCKET_OPTION_SSID` env var, marked `@pytest.mark.integration`)
- [ ] Write unit test with mocked `PocketOptionAsync`

### 2.4 PostgreSQL Persistence

- [ ] Create `infrastructure/persistence/postgres/connection.py`:
  - `create_pool(settings) -> asyncpg.Pool` — connection pool creation with retry
  - `get_pool() -> asyncpg.Pool` — singleton access
- [ ] Create `infrastructure/persistence/postgres/repositories.py`:
  - `PostgresSignalRepository` implements `SignalRepository` — SQLAlchemy async or raw asyncpg queries
  - `PostgresTradeRepository` implements `TradeRepository`
  - `PostgresStrategyRepository` implements `StrategyRepository`
  - `PostgresEventStore` implements `EventStore`
- [ ] Create `infrastructure/persistence/postgres/migrations/`:
  - `001_initial.py` — Alembic migration: signals table, trades table (partitioned by month), strategies table, domain_events table, indices
  - `Alembic env.py` configuration
- [ ] Write integration tests with testcontainers PostgreSQL

### 2.5 Redis Cache & Pub/Sub

- [ ] Implement `infrastructure/persistence/redis/cache.py`:
  - `RedisCache` — `get(key)`, `set(key, value, ttl)`, `delete(key)`, `exists(key)`. Serializes with orjson. Generic type support.
- [ ] Implement `infrastructure/persistence/redis/pubsub.py`:
  - `RedisEventBus` implements `EventBus` — publishes events as JSON to Redis channels, subscribes via `pubsub.subscribe()`
  - `RedisSignalPublisher` — publishes `SignalGenerated` events to `signals:{symbol}` channel for cross-process distribution
- [ ] Implement `infrastructure/persistence/redis/rate_limiter.py`:
  - `RedisRateLimiter` — sliding window via sorted sets. `check(key, max_requests, window_seconds) -> bool`. Per-user and global rate limiting.
- [ ] Write integration tests with testcontainers Redis

### 2.6 ML & Features

- [ ] Implement `infrastructure/features/indicator_registry.py`:
  - `IndicatorRegistry` — maps indicator names to compute functions. Registered at startup. Contains pandas-ta wrappers for RSI, MACD, Bollinger, SMA, EMA, ATR, Stochastic, etc.
- [ ] Implement `infrastructure/features/feature_pipeline.py`:
  - `FeaturePipeline` — `compute(symbol, candles, feature_config) -> dict[str, float]`. Loads history from cache if available, computes each indicator in the config, returns named feature vector.
  - Handles warmup: only returns features once enough history exists for all indicators' periods.
  - Caches intermediate indicator values per symbol to avoid recomputation.
- [ ] Implement `infrastructure/ml/model_service.py`:
  - `ModelService` — loads XGBoost/LightGBM model from MLflow registry (or local file), caches in memory, `predict(features: dict) -> (direction, confidence)`. Handles model versioning.
- [ ] Implement `infrastructure/ml/mlflow_client.py`:
  - `MLflowClient` — wraps MLflow tracking API. `log_experiment(params, metrics, artifacts)`, `register_model(uri, name)`, `load_model(uri)`. Handles run context management.

### 2.7 Data Catalog

- [ ] Implement `infrastructure/research/data_catalog.py`:
  - `DataCatalog` — `get_candles(symbol, timeframe, start, end) -> pd.DataFrame`. Reads from DuckDB (if available), falls back to Parquet files. Caches hot data in memory.
  - `store_candles(symbol, timeframe, df) -> None`. Appends to DuckDB and exports to Parquet.

---

## Phase 3: Application Layer

Orchestrates domain logic. Depends on domain ports only.

### 3.1 Use Cases — Signals

- [ ] Implement `application/use_cases/generate_signal.py`:
  - `GenerateSignalUseCase(broker, feature_pipeline, model_service, signal_repo, event_bus, clock)`
  - `execute(strategy_id, symbol) -> Signal`: get latest candle, compute features, run model prediction, save signal to repo, publish SignalGenerated event, return signal DTO
- [ ] Implement `application/use_cases/get_latest_signal.py`:
  - `GetLatestSignalUseCase(signal_repo)`
  - `execute(symbol) -> Signal|None`: query most recent signal for a symbol
- [ ] Implement `application/use_cases/get_signal_history.py`:
  - `GetSignalHistoryUseCase(signal_repo)`
  - `execute(symbol, since, limit) -> list[Signal]`

### 3.2 Use Cases — Trading

- [ ] Implement `application/use_cases/place_trade.py`:
  - `PlaceTradeUseCase(broker, trade_repo, strategy_repo, risk_calculator, event_bus, clock)`
  - `execute(strategy_id, signal_id, symbol, direction, amount, timeframe) -> Trade`: validate strategy is active, check risk limits, place via broker, save trade, publish TradeOpened event
- [ ] Implement `application/use_cases/execute_signal.py`:
  - `ExecuteSignalUseCase(generate_signal, place_trade, strategy_repo)`
  - `execute(strategy_id, symbol) -> (Signal, Trade|None)`: generates signal, evaluates confidence, places trade if threshold met
- [ ] Implement `application/use_cases/check_pending_trades.py`:
  - `CheckPendingTradesUseCase(broker, trade_repo, event_bus, clock)`
  - `execute()`: iterate open trades, check each for expiry via broker, update results, publish TradeExpired events
- [ ] Implement `application/use_cases/get_portfolio.py`:
  - `GetPortfolioUseCase(broker, trade_repo)`
  - `execute() -> dict`: current balance, open trades, today's PnL, total trades, win rate

### 3.3 Use Cases — Strategy Management

- [ ] Implement `application/use_cases/create_strategy.py`:
  - `CreateStrategyUseCase(strategy_repo)`
  - `execute(config: StrategyConfig) -> Strategy`: validate config, create entity, save
- [ ] Implement `application/use_cases/update_strategy.py`:
  - `UpdateStrategyUseCase(strategy_repo)`
  - `execute(strategy_id, updates) -> Strategy`
- [ ] Implement `application/use_cases/activate_strategy.py`:
  - `ActivateStrategyUseCase(strategy_repo, event_bus)`
  - `execute(strategy_id)`: set status=ACTIVE, publish StrategyActivated event
- [ ] Implement `application/use_cases/list_strategies.py`:
  - `ListStrategiesUseCase(strategy_repo)`
  - `execute(status_filter|None) -> list[Strategy]`

### 3.4 DTOs

- [ ] Implement `application/dto/signal_dto.py`:
  - `SignalDTO`, `SignalDetailDTO` — Pydantic models for API response, flatten/rename domain fields
- [ ] Implement `application/dto/trade_dto.py`:
  - `TradeDTO`, `TradeDetailDTO`, `TradeResultDTO`
- [ ] Implement `application/dto/portfolio_dto.py`:
  - `PortfolioDTO(balance, open_trades, daily_pnl, total_trades, win_rate, today_trades)`
- [ ] Implement `application/dto/strategy_dto.py`:
  - `StrategyDTO`, `StrategyCreateDTO`, `StrategyUpdateDTO`
- [ ] Implement `application/dto/backtest_dto.py`:
  - `BacktestRequestDTO`, `BacktestResultDTO(metrics, trades, equity_curve)`

### 3.5 Application Tests

- [ ] Write tests for each use case with mocked ports
- [ ] Verify use cases only call port methods — no infrastructure imports
- [ ] Verify error handling: broker failure, repository failure, validation failure

---

## Phase 4: Engine Layer

Orchestrates the live trading loop.

### 4.1 Orchestrator

- [ ] Implement `engine/orchestrator.py`:
  - `Orchestrator` — manages system lifecycle
  - `start()`: load settings, init DB pool, init Redis, connect broker, load active strategies, start pipeline tasks
  - `shutdown()`: cancel all tasks, disconnect broker, close DB pool, close Redis
  - State machine: `CREATED → STARTING → RUNNING → STOPPING → STOPPED`

### 4.2 Signal Pipeline

- [ ] Implement `engine/signal_pipeline.py`:
  - `SignalPipeline(strategy, broker, feature_pipeline, model_service, execute_signal_uc, event_bus)`
  - `run()`: subscribe to strategy's symbols, for each candle: execute signal → evaluate confidence → optionally trade. Runs as an `async with TaskGroup` task.
  - `stop()`: unsubscribe, cancel iteration

### 4.3 Trade Monitor

- [ ] Implement `engine/trade_monitor.py`:
  - `TradeMonitor(check_pending_uc, event_bus)`
  - `run()`: every N seconds (configurable), check pending trades for expiry. Publishes `TradeExpired` events. Runs as background task.
  - Configurable check interval (default 5s for 60s options, adjust based on shortest active timeframe)

### 4.4 Broker Health Monitor

- [ ] Implement `engine/broker_monitor.py`:
  - `BrokerMonitor(broker, event_bus)`
  - Monitors connection state via `on_disconnect` async generator and periodic health pings
  - Publishes `BrokerDisconnected` / `BrokerReconnected` events
  - Logs connection state changes with structured context

---

## Phase 5: Interfaces Layer

### 5.1 Telegram Bot — Configuration & Wiring

- [ ] Implement `interfaces/telegram/config.py`:
  - `TelegramBotConfig(BaseSettings)` — validate all TELEGRAM_* env vars, parse comma-separated user IDs
- [ ] Implement `interfaces/telegram/main.py`:
  - Entry point: `python -m interfaces.telegram.main`
  - Creates Application, registers handlers, calls `run_polling()` or `run_webhook()`
- [ ] Implement `interfaces/telegram/bot.py`:
  - `create_application(settings, use_cases) -> Application` — wires PTB ApplicationBuilder with handlers, rate limiter, persistence
  - `post_init(application)`: validate broker connection, load strategies
  - `post_shutdown(application)`: clean disconnect

### 5.2 Telegram Bot — Handlers

- [ ] Implement `interfaces/telegram/handlers/base.py`:
  - `authorized_only(func)` — decorator that checks `update.effective_user.id` against allowed list. Replies "Access denied" if not authorized.
  - `admin_only(func)` — decorator that checks admin list.
  - `rate_limited(func)` — decorator that checks per-user rate limit via RedisRateLimiter.
  - `extract_user(update) -> int` — helper to extract Telegram user ID
- [ ] Implement `interfaces/telegram/handlers/start.py`:
  - `/start` — welcome message, feature overview, quick start guide
  - `/help` — list all commands with descriptions
- [ ] Implement `interfaces/telegram/handlers/signals.py`:
  - `/signal <symbol>` — get latest signal for symbol. Calls `GetLatestSignalUseCase`. Shows direction, confidence, timestamp, features.
  - `/subscribe <symbol>` — subscribe to signal notifications for symbol. Stores subscription in Redis per user. (Requires conversation flow.)
  - `/unsubscribe <symbol>` — remove subscription.
  - `/subscriptions` — list active subscriptions with last signal summary.
- [ ] Implement `interfaces/telegram/handlers/trading.py`:
  - `/trade <symbol> <amount>` — execute signal and place trade. Calls `ExecuteSignalUseCase`. Shows trade confirmation with ID, amount, expiry time.
  - `/status <trade_id>` — check status/result of a trade.
  - `/portfolio` — current balance, open trades, today's PnL. Calls `GetPortfolioUseCase`.
- [ ] Implement `interfaces/telegram/handlers/strategies.py`:
  - `/strategies` — list active strategies with performance summary.
  - `/strategy <name>` — show strategy details (symbols, timeframe, current stats).
  - `/activate <name>` — activate a strategy.
  - `/pause <name>` — pause a strategy.
- [ ] Implement `interfaces/telegram/handlers/admin.py`:
  - `/broadcast <message>` — send message to all subscribed users (admin only).
  - `/stats` — system health, active connections, daily trade count (admin only).
  - `/restart` — graceful restart of pipeline (admin only).
  - `/logs <level> <count>` — tail last N log lines at given level (admin only).

### 5.3 Telegram Bot — Conversations

- [ ] Implement `interfaces/telegram/conversations/subscribe_flow.py`:
  - ConversationHandler with states: `SELECT_SYMBOL`, `CONFIRM_TIMEFRAME`, `SET_AMOUNT`, `CONFIRM`
  - Guides user through subscribing to a symbol with configuration
  - Stores subscription in Redis with user preferences (symbol, timeframe, min_confidence, max_amount)
- [ ] Implement `interfaces/telegram/conversations/trade_flow.py`:
  - ConversationHandler: `SELECT_SYMBOL`, `ENTER_AMOUNT`, `SELECT_DIRECTION`, `CONFIRM_TRADE`
  - Validates each step before proceeding. Shows summary before final confirmation.

### 5.4 Telegram Bot — Presentation

- [ ] Implement `interfaces/telegram/presentation/formatters.py`:
  - `format_signal(signal: Signal) -> str` — formatted message with direction emoji, confidence bar, timestamp, feature table
  - `format_trade(trade: Trade) -> str` — trade card with ID, symbol, direction, amount, entry price, expiry countdown, status badge
  - `format_portfolio(portfolio: PortfolioDTO) -> str` — balance, open trades table, daily PnL, performance stats
  - `format_strategy(strategy: Strategy) -> str` — name, status badge, symbols, performance metrics
  - `format_error(error: DomainError) -> str` — user-friendly error message
- [ ] Implement `interfaces/telegram/presentation/menus.py`:
  - `main_menu() -> InlineKeyboardMarkup` — Signal, Trade, Portfolio, Settings buttons
  - `signal_menu(symbols) -> InlineKeyboardMarkup` — inline buttons for symbol selection
  - `confirmation_menu() -> InlineKeyboardMarkup` — Confirm/Cancel buttons

### 5.5 Telegram Bot — Notifications

- [ ] Implement `interfaces/telegram/notifier.py`:
  - `TelegramNotifier(application, settings)` — maintains mapping of user_id → subscriptions
  - `notify_signal(user_id, signal)` — sends signal notification to subscribed user
  - `notify_trade_result(user_id, trade)` — sends trade result (win/loss, profit)
  - `notify_alert(user_id, message)` — sends system alert (disconnected, error, etc.)
  - Subscribes to event bus events (`SignalGenerated`, `TradeOpened`, `TradeExpired`, `BrokerDisconnected`) and routes to appropriate notification methods

### 5.6 FastAPI Interface

- [ ] Implement `interfaces/api/main.py`:
  - FastAPI app with lifespan handler (start/shutdown orchestrator)
  - CORS middleware, request ID middleware, timing middleware, structlog middleware
  - Exception handlers for `DomainError` subclasses → proper HTTP error responses
- [ ] Implement `interfaces/api/deps.py`:
  - `get_orchestrator()` — dependency that yields the running orchestrator instance
  - `get_signal_uc()`, `get_trade_uc()`, etc. — use case factory deps
  - `verify_token()` — JWT auth dependency (placeholder for now)
- [ ] Implement `interfaces/api/v1/signals.py`:
  - `GET /v1/signals/{symbol}/latest` — latest signal
  - `GET /v1/signals/{symbol}/history` — signal history with since/limit params
- [ ] Implement `interfaces/api/v1/trades.py`:
  - `GET /v1/trades` — trade history with filters
  - `GET /v1/trades/{id}` — single trade detail
  - `POST /v1/trades` — place trade from signal
  - `GET /v1/trades/open` — currently open trades
- [ ] Implement `interfaces/api/v1/strategies.py`:
  - `GET /v1/strategies` — list strategies
  - `POST /v1/strategies` — create strategy
  - `GET /v1/strategies/{id}` — strategy detail
  - `PATCH /v1/strategies/{id}` — update strategy
  - `POST /v1/strategies/{id}/activate` — activate
  - `POST /v1/strategies/{id}/pause` — pause
- [ ] Implement `interfaces/api/v1/portfolio.py`:
  - `GET /v1/portfolio` — current portfolio view
  - `GET /v1/portfolio/history` — historical PnL
- [ ] Implement `interfaces/api/v1/admin.py`:
  - `GET /v1/admin/health` — health check
  - `GET /v1/admin/metrics` — prometheus metrics

### 5.7 CLI Interface

- [ ] Implement `interfaces/cli/commands.py`:
  - `trade-cli start` — start orchestrator (live mode)
  - `trade-cli backtest <strategy>` — run backtest
  - `trade-cli signal <symbol>` — get latest signal
  - `trade-cli portfolio` — show portfolio
  - `trade-cli download <symbol> <start> <end>` — download historical data
  - `trade-cli train <strategy>` — train ML model for strategy
  - `trade-cli validate <strategy>` — run walk-forward validation

---

## Phase 6: Backtesting & Research

### 6.1 Backtest Engine

- [ ] Implement `infrastructure/research/backtest_engine.py`:
  - `BacktestEngine` — takes strategy config + historical data. Runs vectorized pass first (fast), then event-driven pass (accurate).
  - Vectorized: compute all indicators at once, generate signal series, simulate trade outcomes, compute metrics.
  - Event-driven: same code path as live pipeline, uses BacktestBroker.
  - Output: `BacktestResult(metrics: BacktestMetrics, trades: list[Trade], equity_curve: pd.Series)`.
- [ ] Implement `infrastructure/research/walk_forward.py`:
  - `WalkForwardValidator` — splits data into N train/test windows. For each window: train on train set, test on test set, combine results. Returns cross-validation metrics + stability analysis.

### 6.2 Backtest Use Case

- [ ] Implement `application/use_cases/run_backtest.py`:
  - `RunBacktestUseCase(backtest_engine, strategy_repo, data_catalog, mlflow_client)`
  - `execute(strategy_id, start_date, end_date, params_override|None) -> BacktestResultDTO`

### 6.3 Research Experiment Tracking

- [ ] Implement `infrastructure/ml/experiment_tracker.py`:
  - `ExperimentTracker` — wraps MLflow. `start_run(config, strategy_id)`, `log_metrics(metrics)`, `log_params(params)`, `log_artifact(path)`, `log_dataset(digest)`, `end_run()`.
  - Links each experiment run to: git commit hash, dataset version (DVC), configuration hash, strategy version.

---

## Phase 7: Risk Management

### 7.1 Risk Pipeline

- [ ] Implement `engine/risk_manager.py`:
  - `RiskManager(strategy, trade_repo, clock)` — subscribes to SignalGenerated events
  - `evaluate(signal) -> (APPROVED|REJECTED, reason|None)`
  - Rules: max daily trades per strategy, max concurrent open trades, cooldown since last trade, max daily loss limit, circuit breaker (N consecutive losses → pause strategy)
  - Publishes `TradeApproved(signal, position_size)` or `TradeRejected(signal, reason)` events

### 7.2 Trade Executor

- [ ] Implement `engine/trade_executor.py`:
  - `TradeExecutor(broker, trade_repo, event_bus)` — subscribes to TradeApproved events
  - `execute(event)`: calls `broker.place_option(...)` with retry (max 3 attempts, exponential backoff). On success: save trade, publish TradeOpened. On all retries failed: publish TradeFailed.

---

## Phase 8: Integration & Wiring

### 8.1 Composition Root

- [ ] Implement `interfaces/telegram/bot.py` DI wiring:
  - Instantiate all infrastructure: PostgreSQL pool, Redis, BrokerAdapter, FeaturePipeline, ModelService
  - Instantiate all repositories: PostgresSignalRepository, PostgresTradeRepository, PostgresStrategyRepository
  - Instantiate all use cases with their dependencies
  - Instantiate event bus and subscribe all pipeline components
  - Instantiate Telegram handlers with use case references
  - Return built PTB Application

### 8.2 Entry Points

- [ ] Create `interfaces/telegram/__main__.py`:
  - Load settings, build composition root, run bot
- [ ] Create `interfaces/api/__main__.py`:
  - Load settings, create FastAPI app, run with uvicorn
- [ ] Create `interfaces/cli/__main__.py`:
  - Load settings, dispatch CLI commands

### 8.3 Docker Entry Points

- [ ] Create `docker/entrypoints/bot.sh` — starts Telegram bot service
- [ ] Create `docker/entrypoints/api.sh` — starts FastAPI service
- [ ] Create `docker/entrypoints/worker.sh` — starts background worker (trade monitor, etc.)

---

## Phase 9: Production Hardening

### 9.1 Monitoring

- [ ] Add Prometheus metric instrumentation to:
  - Signal pipeline (signals generated, generation latency)
  - Trade executor (trades placed, success/failure rate)
  - Broker adapter (connection state, reconnect count, candle throughput)
  - Event bus (queue depth, handler latency)
- [ ] Add health check endpoints to FastAPI app
- [ ] Add structured logging to all pipeline stages
- [ ] Create Grafana dashboard config (JSON model) for: signal rate, trade PnL, broker health, system resources

### 9.2 Error Recovery

- [ ] Implement graceful shutdown in Orchestrator: TaskGroup cancellation, drain queues, flush pending trades, close connections
- [ ] Implement broker reconnection monitoring: exponential backoff, max retry cap, notify on persistent failure
- [ ] Implement trade reconciliation on reconnect: query broker for trades placed during disconnect, reconcile with local state

### 9.3 Security

- [ ] Implement SSID encryption at rest (Fernet symmetric encryption) for stored sessions
- [ ] Implement Telegram message sanitization (strip markdown injection)
- [ ] Implement API authentication (JWT bearer tokens for FastAPI)
- [ ] Implement rate limiting on all API endpoints

### 9.4 Documentation

- [ ] Write API docs with OpenAPI/Swagger (auto from FastAPI)
- [ ] Write `README.md` with setup instructions, architecture overview, command reference
- [ ] Document SSID acquisition procedure (how to get SSID from browser)
- [ ] Document deployment procedures for polling and webhook modes

---

## Dependency Map

```
Phase 0 ────► Phase 1 ────► Phase 2 ────► Phase 3 ────► Phase 4 ────► Phase 5
                    │            │              │                         │
                    │            │              │                         ▼
                    │            │              │                   Phase 8
                    │            │              │                         │
                    ▼            ▼              ▼                         ▼
              Phase 6 ◄──── Phase 7 ◄────────────────────────────── Phase 9
```

- Phase 0 must be complete before anything else
- Phase 1 has no dependencies on infrastructure — can be built and tested immediately
- Phase 2 depends on Phase 1 (ports)
- Phase 3 depends on Phase 1 (ports) and Phase 2 (infrastructure implementations)
- Phase 4 depends on Phase 3 + Phase 2
- Phase 5 depends on Phase 3 + Phase 4
- Phase 6, 7 can be built in parallel after Phase 2
- Phase 8 wires everything together — depends on Phase 5
- Phase 9 is ongoing once Phase 8 is running

---

## Task Count: ~90 implementable tasks

Each task is sized to be implementable independently (typically 1-2 files, 50-200 lines). No task requires more than one engineer-day of work.
