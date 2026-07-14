# Architecture Report: Binary Options Research & Signal-Generation Platform

**Author:** Joseph Smart Karalee  
**Date:** June 2026  
**Status:** Draft for Review  
**Version:** 1.0.0

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [BinaryOptionsTools-v2 Analysis](#2-binaryoptionstools-v2-analysis)
3. [Competitive Analysis](#3-competitive-analysis)
4. [Recommended Technology Stack](#4-recommended-technology-stack)
5. [Recommended System Architecture](#5-recommended-system-architecture)
6. [Domain Design](#6-domain-design)
7. [Data Flow](#7-data-flow)
8. [Engineering Principles](#8-engineering-principles)
9. [Risk Analysis](#9-risk-analysis)
10. [Open Questions](#10-open-questions)
11. [Final Recommendations](#11-final-recommendations)

---

## 1. Executive Summary

This report presents the architectural foundation for a professional binary options research and signal-generation platform. The platform is designed to outlive any single client interface. Telegram is the first client, but the architecture explicitly supports REST API, Web Dashboard, Mobile App, and Auto Trading as future interface channels without requiring core engine changes.

### Core Architectural Decision

The platform extends BinaryOptionsTools-v2 — it does not replace it. BinaryOptionsTools-v2 provides a mature Rust-based WebSocket client, broker interaction layer, strategy execution hooks, and virtual market. Our platform builds the research, signal generation, ML, persistence, orchestration, and interface layers on top. This avoids rewriting a proven, battle-tested broker communication library while giving us full control over the research and signal generation stack.

### Key Findings

| Finding | Conclusion |
|---------|-----------|
| BinaryOptionsTools-v2 architecture | Well-structured Rust core with PyO3 bindings. Reuse the Rust client, extend the Python strategy layer. |
| Best architectural reference | NautilusTrader provides the closest production-grade pattern: Rust core + Python control plane. |
| Backtesting approach | Hybrid: vectorized (NumPy/Numba) for research speed, event-driven (BinaryOptionsTools-v2 VirtualMarket) for production realism. |
| Feature engineering | Pandas-ta as primary API, TA-Lib as optional accelerator. Polars for batch ETL. |
| ML stack | XGBoost + LightGBM for gradient boosting, scikit-learn for pipelines, Optuna for hyperparameter search, MLflow for experiment tracking. |
| Data storage | PostgreSQL for live state, DuckDB for research/analytics, Redis for cache/pub-sub. |
| Interface architecture | Clean Architecture layering ensures Telegram, REST API, Dashboard, and Mobile share the same domain and application layers. |
| Deployment | Docker Compose for development, multi-stage Docker builds for production. |

### Architecture Philosophy

```
Never couple the engine to a single interface.
Never embed business logic in a presenter.
Never depend on infrastructure in the domain.
```

The platform follows Clean Architecture, Domain-Driven Design, and SOLID principles. Every component has a single responsibility. Dependencies point inward: Infrastructure → Application → Domain. Interfaces (Telegram, REST, Dashboard) are thin adapters that translate between the external world and application use cases.

---

## 2. BinaryOptionsTools-v2 Analysis

### 2.1 Architecture Overview

BinaryOptionsTools-v2 (v0.2.11) is a Rust-native library with Python bindings via PyO3. Its architecture is layered:

```
┌─────────────────────────────────────────────────┐
│              Python SDK Layer                     │
│  PocketOptionAsync  PocketOption  PyBot  PyStrategy│
├─────────────────────────────────────────────────┤
│              PyO3 Bindings Layer                  │
│  RawPocketOption  StrategyWrapper  PyVirtualMarket │
├─────────────────────────────────────────────────┤
│         BinaryOptionsTools Crate                  │
│  PocketOption  Bot  Strategy  VirtualMarket       │
├─────────────────────────────────────────────────┤
│              Core Crate                           │
│  Client  Router  Middleware  Connector  Signals    │
├─────────────────────────────────────────────────┤
│         WebSocket (tokio-tungstenite)             │
│              Socket.IO 4.x                        │
└─────────────────────────────────────────────────┘
```

### 2.2 Component Breakdown

#### Core Crate (`crates/core/`)

A generic WebSocket client framework. Not PocketOption-specific.

- **`Client<S: AppState>`**: Public handle — send messages, disconnect, reconnect. Holds signal watchers, state, module handles, and channel senders.
- **`ClientRunner<S>`**: Manages the full WebSocket lifecycle. Connect → writer/reader tasks → reconnect loop with exponential backoff. Runs as a `tokio::spawn` task.
- **`Router<S>`**: Routes incoming messages through middleware, then to lightweight handlers, lightweight modules (via rules), and API modules (via rules).
- **`MiddlewareStack<S>`**: Hooks: `on_connect`, `on_disconnect`, `on_send`, `on_receive`, `record_connection_attempt`.
- **`Signals`**: `wait_connected()` / `wait_disconnected()` for connection state notification.
- **`Connector<S>` trait**: Interface for platform-specific connect/reconnect/disconnect.

Communication between core and modules uses **kanal** async channels — bounded, MPSC, with optional sync senders.

#### BinaryOptionsTools Crate (`crates/binary_options_tools/`)

The high-level platform client and strategy framework.

- **`PocketOption` struct** (~1430 lines): Full broker client. Handles Socket.IO handshake, SSID auth, initialization sequence, and 12 API modules.
- **Modules** (each implementing `ApiModule` or `LightweightModule`):
  - `keep_alive`, `balance`, `server_time`, `assets` (lightweight — no rules)
  - `trades`, `deals`, `subscriptions`, `get_candles`, `historical_data`, `pending_trades`, `raw` (full API modules with rules)
- **`Strategy` trait**: `on_start`, `on_candle`, `on_tick`, `on_deal_opened`, `on_deal_closed`, `on_balance_update`.
- **`Bot` struct**: Orchestrates strategy execution. Subscribes to assets, runs a `select!` loop over combined candle streams, calls strategy hooks.
- **`VirtualMarket` struct**: Paper trading simulator. Implements `Market` trait. Simulates balance, trades, price updates, expiry resolution.
- **`Config` struct**: Connection parameters, subscription limits, timeouts.
- **`Validator` enum**: Pattern-matching system for WebSocket messages. Supports `StartsWith`, `EndsWith`, `Contains`, `Regex`, `Not`, `All`, `Any`, `Custom`.
- **`Candle` / `BaseCandle` / `SubscriptionType`**: Candle data structures and four subscription modes (raw, chunked, timed, time-aligned).

#### PyO3 Bindings (`crates/bindings_pyo3/`)

- **`RawPocketOption`** (~1123 lines): Python-accessible class wrapping Rust `PocketOption`. Exposes all operations as async methods via `future_into_py`. Streams return `StreamIterator` or `RawStreamIterator`.
- **`PyStrategy`**: Python-subclassable class. Methods: `on_start`, `on_candle`, `on_balance`, `trade`, `result`, `add` (indicator), `get` (indicator), `update`, `reset`, `period`.
- **`StrategyWrapper`**: Bridges Python ↔ Rust. Uses `Python::attach(|py| ...)` with `tokio::task::spawn_blocking` for GIL-safe calls from async Rust.
- **`PyVirtualMarket`**: Python wrapper around `VirtualMarket`.
- **`RawValidator`**: Python-compatible enum mirroring Rust validator.
- **`PyConfig`**: Python-compatible config with `from_dict`, `from_json`.

#### Python SDK (`python/BinaryOptionsToolsV2/`)

- **`asynchronous.py` — `PocketOptionAsync`**: Primary Python API. Wraps `RawPocketOption` with SSID validation, JSON parsing, type hints, `check_win` classification, async context manager, `AsyncSubscription` wrapper.
- **`synchronous.py` — `PocketOption`**: Synchronous wrapper around `PocketOptionAsync` using `asyncio.run()`.
- **`validator.py`**: High-level `Validator` class with static factory methods.
- **`config.py`**: Python `Config` dataclass.

### 2.3 Strengths

| Strength | Detail |
|----------|--------|
| **Performance** | Rust core with zero-cost abstractions. No GIL on hot paths (WebSocket I/O, message routing, candle aggregation). |
| **Comprehensive API** | Every PocketOption feature mapped: trades, deals, pending orders, raw WebSocket, assets, history, subscriptions. |
| **Robust reconnection** | Exponential backoff with jitter (±20%), max backoff 3600s, stable connection reset (10s), hard/soft reconnect modes. |
| **Dual API surface** | Async (`PocketOptionAsync`) and sync (`PocketOption`) Python clients. Context manager support. |
| **Virtual market** | Full `Market` trait implementation. Strategies run unchanged in paper mode. Balance, trade simulation, expiry resolution. |
| **Raw WebSocket access** | `RawHandler` + `Validator` system provides full Socket.IO protocol access for advanced use cases. |
| **Candle aggregation** | Four subscription modes: raw, chunked, timed, time-aligned. Covers all streaming use cases. |
| **Trade deduplication** | Fingerprint-based duplicate prevention. Reconciliation on reconnect. |
| **Multi-language** | UniFFI bindings for Kotlin, Swift, Go, C#, Ruby, JS (in addition to Python). |
| **Strategy warmup** | Built-in warmup cycle: calls `update(candle)` until `current_candle >= period()`, then enables strategy `on_candle`. |

### 2.4 Weaknesses

| Weakness | Impact | Mitigation Strategy |
|----------|--------|-------------------|
| **PocketOption-only** | Locked to one broker. ExpertOption is alpha, IQ Option is roadmap. | Abstract broker interface in our domain layer. Write PocketOption adapter. Future brokers require adapter only. |
| **SSID dependency** | Requires manual browser cookie extraction. No login/password auth. | Accept as a constraint for now. Document SSID refresh procedure. Consider session persistence in our platform. |
| **No market data persistence** | No built-in DB or CSV logging. Data lives only in memory. | Implement persistence layer in our infrastructure. Capture candles, ticks, trades to PostgreSQL + Parquet. |
| **Virtual market is basic** | Simple price comparison for win/loss. No spread, slippage, or latency simulation. | Extend VirtualMarket with configurable spread, slippage model, latency simulation. |
| **Limited test coverage** | Python tests exist but Rust tests require live `POCKET_OPTION_SSID`. | Maintain integration tests with real broker. Use WebSocket mocking (`TestingWrapper`) for unit tests. |
| **No rate limiting** | No explicit API call throttling. | Implement rate limiter in our adapter layer before calling BinaryOptionsTools-v2. |
| **Single account per instance** | One SSID per client instance. | Support multi-account via multiple client instances managed by our platform. |
| **Subscription limit** | Hardcoded max subscriptions (default 4). | Configurable in our wrapper. Increase if broker allows. |
| **License** | Personal use only. Commercial requires permission. | Verify licensing for our use case. Contact ChipaDevTeam if commercial. |

### 2.5 Extension Points

The library provides several well-designed extension points:

| Extension Point | Mechanism | Our Usage |
|----------------|-----------|-----------|
| **Custom strategies** | Subclass `PyStrategy` in Python. | Our strategy framework will produce `PyStrategy` subclasses with ML integration. |
| **Custom indicators** | `PyStrategy.add(name, indicator)` — any Python object with `update(candle)`, `reset()`, `period()`. | Our indicator pipeline will produce objects matching this protocol. |
| **Virtual market** | `PyVirtualMarket` — swap in paper mode without changing strategy code. | Use for backtesting and paper trading in our platform. |
| **Raw WebSocket API** | `RawHandler` + `Validator` — arbitrary Socket.IO messages. | Use for features not exposed by the standard API. |
| **Config injection** | `PyConfig` — configurable connection parameters. | Manage configuration externally, inject via our platform. |

### 2.6 Limitations to Accept

These are architectural constraints we should work around, not fight:

1. **The strategy execution loop lives inside BinaryOptionsTools-v2.** `PyBot.run()` is a blocking loop (even if async). We cannot easily inject our own preprocessing between the WebSocket and the strategy. Workaround: design our strategy as a thin proxy that delegates to our pipeline via events/queues.

2. **No ML integration.** The `PyStrategy` API is designed for rule-based indicators. ML inference must happen outside the strategy hook or we must bridge it ourselves.

3. **No database or state persistence.** The library is stateless by design. All state management is our responsibility.

4. **Candle data arrives as JSON strings.** The library does not parse candles into typed Python objects — `on_candle(ctx, asset, candle_json)` gives you a raw string.

5. **No backtesting framework beyond VirtualMarket.** There is no walk-forward, no performance metrics, no parameter optimization.

### 2.7 Recommended Integration Approach

```
┌────────────────────────────────────────────────────────┐
│                   Our Platform (Python)                  │
│                                                         │
│  ┌──────────┐  ┌────────────┐  ┌────────────────────┐  │
│  │ Telegram  │  │ FastAPI    │  │ Research Notebooks │  │
│  │ Interface │  │ Interface  │  │ (Jupyter)          │  │
│  └─────┬─────┘  └─────┬──────┘  └─────────┬──────────┘  │
│        │               │                   │             │
│  ┌─────┴───────────────┴───────────────────┴──────────┐  │
│  │            Application Layer (Use Cases)             │  │
│  │  SignalService  StrategyService  BacktestService    │  │
│  └─────┬──────────────────────────────────────┬───────┘  │
│        │                                      │         │
│  ┌─────┴──────────────────┐  ┌────────────────┴───────┐ │
│  │   Domain Layer         │  │  Infrastructure Layer   │ │
│  │  Signal  Trade  Strategy│  │  PostgreSQL  Redis      │ │
│  │  FeatureSet  Indicator │  │  DuckDB  Parquet Store  │ │
│  └─────┬──────────────────┘  └────────────────────────┘ │
│        │                                                │
└────────┼────────────────────────────────────────────────┘
         │
┌────────┴────────────────────────────────────────────────┐
│           BinaryOptionsTools-v2 (Rust + PyO3)            │
│  PyBot  PyStrategy  VirtualMarket  PocketOptionAsync    │
│  WebSocket (tokio-tungstenite) → PocketOption Server     │
└─────────────────────────────────────────────────────────┘
```

**Integration rules:**

1. Our platform **drives** BinaryOptionsTools-v2, never the reverse.
2. BinaryOptionsTools-v2 is an **infrastructure dependency** — treat it like a database driver, not a framework.
3. Create an **adapter interface** in our domain layer (`BrokerPort`) that abstracts BinaryOptionsTools-v2 behind a protocol. This lets us swap brokers or mock for testing.
4. Keep BinaryOptionsTools-v2 imports **inside infrastructure/** only. Domain and application layers must never import `binaryoptionstoolsv2`.
5. Our strategy logic runs **outside** `PyBot.run()`. Use a minimal `PyStrategy` bridge that pushes data into our event pipeline.

---

## 3. Competitive Analysis

### 3.1 Platform Comparison

| Dimension | Freqtrade | QuantConnect LEAN | Backtrader | VectorBT | NautilusTrader | Hummingbot |
|-----------|-----------|-------------------|------------|----------|----------------|------------|
| **Language** | Python | C# (Python API via CLI) | Python | Python | Rust + Python | Python |
| **Primary use** | Crypto bot | Multi-asset algo | Backtesting | Research | Production algo | Market making |
| **Strategy pattern** | IStrategy interface | QCAlgorithm | Strategy class | Indicator factory | Actor model | Controller/Executor |
| **Backtesting** | Event-driven | Event-driven | Event-driven | Vectorized | Event-driven | Event-driven |
| **ML integration** | External only | External only | External only | Built-in sweeps | External only | External only |
| **Plugin system** | Pluggable (pairlist, protection, exchange) | Modular (data, brokerage, transaction) | Observer/analyzer | Minimal | Actor/component | Connector/strategy |
| **Data pipeline** | Download → Store → Load → Analyze | Subscription manager + consolidators | Data feeds | NumPy arrays | Data Catalog | Queue-based |
| **Live trading** | Full support | Full support | Not built-in | Not built-in | Full support | Full support |
| **Configuration** | JSON config | Algorithm.cs parameters | Parameters in code | Script-based | TOML config | YAML config |
| **Hyperopt** | Built-in (multi-pass) | Not built-in | Not built-in | Built-in (grid search) | Optuna integration | Not built-in |
| **Rust core** | No | No | No | Optional Rust kernels | Yes (core engine) | No |
| **Stars (approx)** | 52k | 20k | 22k | 8k | 24k | 19k |

### 3.2 Ideas Worth Adopting

#### From NautilusTrader (highest priority)

| Idea | Why | How We Apply |
|------|-----|-------------|
| **Rust core + Python control plane** | Performance-critical path in Rust, flexibility in Python. BinaryOptionsTools-v2 already follows this pattern. | Keep BinaryOptionsTools-v2 Rust core. Build Python domain/application layers on top. |
| **Data Catalog** | A single interface for historical data regardless of source (file, DB, broker API). Provides caching, validation, and metadata. | Implement a `DataCatalog` class that abstracts data provenance. Lets backtesting and live modes consume data uniformly. |
| **Actor-based strategies** | Stateful, message-passing components for strategy composition. Each component owns its state and communicates via messages. | Use event-driven architecture. Signal generators, risk managers, and executors communicate via typed events. |
| **Explicit separation of backtest and live modes** | `LiveEngine` vs `BacktestEngine` — same strategy code, different execution environments. | Our `BrokerPort` abstraction enables backtest (virtual), paper (virtual with live data), and live modes. |
| **Identifiers as value objects** | `InstrumentId`, `TraderId`, `StrategyId` are typed, not strings. Prevents confusion and validates at the type level. | Use Pydantic-validated value objects for `Symbol`, `StrategyId`, `TradeId`. |

#### From Freqtrade

| Idea | Why | How We Apply |
|------|-----|-------------|
| **Hybrid computation model** | Vectorized indicators for speed, event-driven trade execution for realism. | Compute indicators with pandas-ta/numpy in batches, execute trades via BinaryOptionsTools-v2 event loop. |
| **Protection system** | Built-in circuit breakers (max drawdown, cooldown, etc.) prevent reckless trading. | Implement protection layer between signal generation and trade execution. Freqtrade's protection model is directly applicable to binary options (cooldown after loss, max daily trades, etc.). |
| **Backtest detail** | Stores every trade with entry/exit reason, profit, duration, tags. | Our `Trade` entity must capture full metadata for post-mortem analysis. |

#### From Backtrader

| Idea | Why | How We Apply |
|------|-----|-------------|
| **Lines abstraction** | Time series as composable, length-managed arrays. Indicators and data feeds both produce Lines. | Adopt a similar composable abstraction for our indicators and features. Each `Feature` produces a typed time series. |
| **Observer pattern** | Analytics (drawdown, Sharpe, trade stats) as pluggable observers on the strategy loop. | Implement observers as event subscribers. Each observer receives trade/signal events and updates its metrics independently. |

**Note:** Backtrader is effectively dead (last commit 2022, issues accumulating). We adopt design patterns, not the library.

#### From VectorBT

| Idea | Why | How We Apply |
|------|-----|-------------|
| **Vectorized research** | 10-100x speed for parameter sweeps and indicator computation. Essential for research productivity. | Use vectorized computation (NumPy/Numba) for research backtests. Export winning parameters to event-driven production. |
| **Indicator factory** | Generic factory that composes UDFs into fully-optimized indicator pipelines. | Our `FeaturePipeline` follows a similar factory pattern. Features are composable, typed, and independently testable. |
| **Portfolio analytics** | `from_signals()` gives complete performance attribution from a signal series. | Implement similar portfolio-level analytics for our backtest results. |

#### From QuantConnect LEAN

| Idea | Why | How We Apply |
|------|-----|-------------|
| **Subscription/consolidator pattern** | Data subscriptions + consolidators that aggregate raw data into desired resolutions. | BinaryOptionsTools-v2 already has four subscription modes. Map these to a standardized subscription interface. |
| **Algorithm Framework** | Alpha → Insight → Portfolio → Execution pipeline. Each phase is pluggable and independently testable. | Our signal generation pipeline mirrors this: Feature extraction → Signal generation → Confidence scoring → Execution decision. |

#### From Hummingbot

| Idea | Why | How We Apply |
|------|-----|-------------|
| **Controller/Executor (V2)** | Controller (strategy logic) is separate from Executor (order lifecycle). Enables swapping strategies on running instances. | Our architecture separates signal generation (Controller) from trade execution (Executor). This allows hot-swapping strategies. |
| **Connector abstraction** | Each exchange is a pluggable connector behind a unified interface. | Our `BrokerPort` abstraction mirrors this. BinaryOptionsTools-v2 for PocketOption, custom adapters for future brokers. |

### 3.3 Things to Avoid

| Anti-Pattern | Source | Why to Avoid |
|-------------|--------|-------------|
| **Frestrat monolithic strategy** | Freqtrade | `IStrategy` interface is 1900+ lines with 20+ methods. Violates Interface Segregation. |
| **No typing** | Backtrader | Everything is duck-typed. Impossible to add static analysis. |
| **Backtrader's parameter system** | Backtrader | Magic `params` tuple attribute. Use Pydantic models instead. |
| **LEAN's C# dependency** | QuantConnect | Excellent architecture but C# ecosystem limits Python ecosystem access. |
| **VectorBT's PRO licensing** | VectorBT | Commercial features gated behind PRO subscription. Keep research stack open-source. |
| **Hummingbot's V1 monolithic connector** | Hummingbot | Single connector handles all exchange logic. V2's split design is strictly better. |
| **No event sourcing** | All except LEAN | Without event storage, backtesting and auditing are limited. Store all domain events. |
| **Pickle for model persistence** | Common anti-pattern | Unstable across Python versions. Use ONNX or MLflow for model versioning. |

---

## 4. Recommended Technology Stack

### 4.1 Stack Overview

```
┌──────────────────────────────────────────────────────┐
│                   PRESENTATION LAYER                   │
│  python-telegram-bot v22+  │  FastAPI + Uvicorn        │
│  Rich (CLI)  │  Jinja2 (Dashboard templates)          │
├──────────────────────────────────────────────────────┤
│                   APPLICATION LAYER                    │
│  Pydantic v2  │  typing.Protocol  │  anyio/task group  │
│  structlog  │  tenacity (retry)                       │
├──────────────────────────────────────────────────────┤
│                   DOMAIN LAYER                         │
│  Pydantic v2 (entities, value objects, events)        │
│  numpy  │  numba  │  decimals                          │
├──────────────────────────────────────────────────────┤
│                   INFRASTRUCTURE LAYER                  │
│  ┌──────────────┬──────────────┬───────────────────┐  │
│  │  PostgreSQL  │   DuckDB     │      Redis         │  │
│  │  (SQLAlchemy)│  (duckdb)    │  (redis-py)        │  │
│  ├──────────────┼──────────────┼───────────────────┤  │
│  │  asyncpg     │  Parquet     │  Prometheus        │  │
│  │  Alembic     │  pyarrow     │  OpenTelemetry     │  │
│  └──────────────┴──────────────┴───────────────────┘  │
│  BinaryOptionsTools-v2  │  httpx  │  MLflow client    │
├──────────────────────────────────────────────────────┤
│                   COMPUTATION ENGINE                   │
│  pandas-ta  │  TA-Lib (optional)  │  XGBoost          │
│  LightGBM  │  scikit-learn  │  Optuna  │  SHAP          │
│  MLflow  │  DVC  │  Polars                             │
├──────────────────────────────────────────────────────┤
│                   DEVOPS                               │
│  uv (dependency)  │  Docker  │  Docker Compose         │
│  GitHub Actions  │  testcontainers  │  Ruff             │
│  Mypy / Pyright  │  Pytest  │  Coverage                │
└──────────────────────────────────────────────────────┘
```

### 4.2 Language

**Python 3.12+** is the correct choice for this platform.

**Why not Rust for everything:**
- Strategy development velocity matters more than raw execution speed for our use case. Python enables rapid iteration, Jupyter notebook exploration, and a larger ML ecosystem.
- BinaryOptionsTools-v2 already provides the Rust core for WebSocket I/O and broker communication.
- Python's async ecosystem (anyio, asyncio) is mature enough for real-time signal generation.

**Why Python 3.12 specifically:**
- Improved error messages (PEP 678 — `__notes__` on exceptions).
- `type` statement syntax (PEP 695) for generic type aliases.
- More `asyncio` improvements and faster CPython.
- All key dependencies support 3.12.

### 4.3 Frameworks and Libraries

#### Domain Modeling

| Library | Purpose | Rationale |
|---------|---------|-----------|
| **Pydantic v2** | All entities, value objects, DTOs, events | Fastest Python validation. Native JSON serialization. `ConfigDict(frozen=True)` for immutability. `model_validate()` for safe deserialization. |
| **typing.Protocol** | Interface definitions | Structural subtyping. Zero runtime overhead. No metaclass magic. Enables dependency inversion without framework. |
| **decimal.Decimal** | All monetary values | Avoids floating-point errors in trade calculations. Matches BinaryOptionsTools-v2's `rust_decimal` precision. |
| **uuid** | Identity generation | Universally unique identifiers for trades, signals, strategies. Avoids auto-increment ID collision risks. |
| **dataclasses** | Internal structures | Lower overhead than Pydantic for internal-only types. |

#### Async Runtime

| Library | Purpose | Rationale |
|---------|---------|-----------|
| **anyio** | Async abstraction | Write once, run on asyncio or trio. TaskGroup, memory channels, semaphores. Better cancellation semantics than bare asyncio. |
| **asyncio** | Standard library runtime | Default backend for anyio. Largest ecosystem, best debugging tools. |
| **TaskGroup** | Structured concurrency | Python 3.11+. All tasks are tracked. Failure in any task cancels the group. Prevents orphaned tasks. |

**Why anyio over bare asyncio:**
- `anyio.TaskGroup` works on both asyncio and trio backends.
- `anyio.Queue` and `MemoryObjectSendStream` provide better cancellation semantics than `asyncio.Queue`.
- `anyio.connect_tcp()`, `connect_unix()`, etc. provide consistent networking across backends.
- If we ever need trio's stronger cancellation guarantees, we can switch without code changes.

**Why not Celery:**
- Overkill for our processing patterns. We have real-time streams (WebSocket → signal), not batch jobs.
- `asyncio.TaskGroup` + `anyio.Queue` handles our concurrency needs with less operational complexity.
- If we need background task queues later, consider `arq` (Redis-backed async queue) or plain `asyncio`.

#### Data Storage

| Database | Purpose | Rationale |
|----------|---------|-----------|
| **PostgreSQL 16** | Live system state | Trades, signals, strategies, users, subscriptions. ACID compliance. JSONB for flexible metadata. Time-based partitioning for trades. |
| **DuckDB 1.x** | Research and analytics | Columnar, vectorized execution. Reads Parquet directly. Perfect for backtesting queries that aggregate millions of candles. In-process — no server to manage. |
| **Redis 7** | Cache, pub/sub, rate limiting | Sub-millisecond reads. Pub/sub for real-time signal distribution. Rate limiting with INCR/EXPIRE. Distributed locks for trade deduplication across processes. |
| **Parquet** | Historical data storage | Columnar format, compressed, splittable. Readable by DuckDB, polars, pandas. Version-controlled via DVC. |

**Why not TimescaleDB:**
- We don't have tick-level data (sub-second). Binary options candles are at minimum 1-second resolution — well within PostgreSQL's capacity with monthly partitioning.
- Continuous aggregates and compression features are useful but not worth the additional infrastructure complexity for our data volume.
- If tick-level storage becomes necessary, TimescaleDB can be added as a PostgreSQL extension without migration.

**Why not MongoDB / NoSQL:**
- Our data is inherently relational: trades reference signals, signals reference strategies, strategies reference configurations.
- JSONB in PostgreSQL provides document-store flexibility where needed (signal parameters, feature metadata).
- ACID compliance matters for trade reconciliation and financial record-keeping.

#### API and Interface

| Library | Purpose | Rationale |
|---------|---------|-----------|
| **FastAPI** | REST API framework | Fastest Python API framework. Built-in OpenAPI validation via Pydantic. Async-native. WebSocket support. Dependency injection via `Depends`. |
| **Uvicorn** | ASGI server | Fastest Python ASGI server. HTTP/1.1 and HTTP/2. WebSocket support. Graceful shutdown via `uvicorn.run()` with `lifespan` protocol. |
| **python-telegram-bot v22+** | Telegram interface | Most mature Python Telegram library. Full asyncio support. Built-in rate limiter, persistence API, conversation handling. |
| **httpx** | HTTP client | Async HTTP for external API calls (market data providers, AI APIs). Connection pooling. HTTP/2 support. |

#### Technical Analysis and Indicators

| Library | Purpose | Rationale |
|---------|---------|-----------|
| **pandas-ta** | Primary indicator library | 150+ indicators. Pandas DataFrame extension (`df.ta.rsi()`). Numba-accelerated. Auto-detects TA-Lib for core indicators. Best developer experience. |
| **TA-Lib** | Optional accelerator | Fastest available. 200+ indicators. C implementation. pandas-ta auto-detects and delegates 34 core indicators. Windows wheel already installed. |
| **numpy** | Array computation | Foundation for all numeric computation. Contiguous memory, vectorized operations. |
| **numba** | JIT compilation | `@njit` for tight computational loops. 50-200x speedup. Essential for custom indicator performance. |
| **polars** | Batch data processing | Multi-core, parallel by default. Streaming and out-of-core for large datasets. Excellent for ETL pipelines and backtesting data prep. |

**Why pandas-ta over TA-Lib as primary:**
- Installation: pandas-ta is pure Python, works everywhere. TA-Lib requires C compiler (or prebuilt wheel, which we have).
- API: pandas-ta's DataFrame extension is more ergonomic than TA-Lib's procedural API.
- Extensibility: Adding custom indicators to pandas-ta is trivial. TA-Lib requires C source modification.
- Coverage: 150+ indicators covers virtually every strategy requirement.
- Performance: When TA-Lib is installed, pandas-ta auto-delegates to it. Best of both worlds.

**Why not write custom pure-numba indicators exclusively:**
- pandas-ta provides battle-tested implementations of 150+ indicators. Reimplementing all of them in numba is a waste of engineering effort.
- Write custom numba indicators only when pandas-ta's implementation is too slow for real-time requirements on your hardware.

#### Machine Learning

| Library | Purpose | Rationale |
|---------|---------|-----------|
| **scikit-learn** | Pipelines, preprocessing, feature selection | `Pipeline` enforces correct transform ordering. `RobustScaler` for outlier handling. `SelectKBest` / `RFECV` for feature selection. `TimeSeriesSplit` for CV. |
| **XGBoost** | Primary gradient boosting | Built-in regularization. Handles missing values. Feature importance. Model serialization. Consistently best performer on tabular financial data. |
| **LightGBM** | Secondary gradient boosting | Faster training on large datasets. Leaf-wise growth often produces better accuracy. Lower memory footprint. |
| **Optuna** | Hyperparameter optimization | Bayesian optimization with pruning. Time-series CV integration. Distributed optimization support. Better than grid search or random search. |
| **SHAP** | Model interpretation | Tree SHAP for XGBoost/LightGBM. Feature importance with direction. Essential for understanding what drives predictions. |
| **MLflow** | Experiment tracking, model registry | Open-source. Self-hostable. Tracks parameters, metrics, artifacts. Model registry with staging/production lifecycle. Widely used in quant workflows. |

**Why not deep learning (PyTorch, TensorFlow):**
- Gradient boosting consistently outperforms neural networks on tabular financial data (see "Why Tree-Based Models Outperform Neural Networks on Tabular Data" — recent benchmark papers).
- Deep learning requires more data, more tuning, more compute.
- Tabular time series data (OHLCV + indicators) is the ideal use case for tree-based models.
- Exception: If we ever add alternative data processing (NLP on news, image processing on charts), PyTorch can be added as an optional dependency.

**Why not H2O / AutoML:**
- Too much magic. We need to understand and control our models.
- AutoML tools hide complexity but sacrifice interpretability and fine-grained control.
- Optuna + XGBoost/LightGBM gives us 90% of the benefit with 100% control.

#### Experiment Tracking and Reproducibility

| Tool | Purpose | Rationale |
|------|---------|-----------|
| **MLflow** | Experiment tracking, model registry | Log parameters, metrics, artifacts per run. Model Registry with versioned deployment. UI for cross-run comparison. |
| **DVC** | Data versioning | Version-controlled datasets. Pipeline stages with explicit inputs/outputs. Links data to git commits for full reproducibility. |
| **Pydantic** | Configuration versioning | Every experiment configuration is a validated Pydantic model. Configs are saved alongside results. |

#### Development and DevOps

| Tool | Purpose | Rationale |
|------|---------|-----------|
| **uv** | Dependency management | 10-100x faster than pip/poetry. Rust-based. Pip-compatible. Lockfile support. Workspaces for monorepo. `uv sync` replaces `pip install -r`. |
| **Docker** | Containerization | Consistent environments from dev to production. Multi-stage builds for minimal images. |
| **Docker Compose** | Local orchestration | PostgreSQL, Redis, application, worker in one command. Enables integration testing locally. |
| **Ruff** | Linting and formatting | 100x faster than flake8/black. Single binary. Pyproject.toml configuration. |
| **Mypy / Pyright** | Static type checking | Strict mode. Verifies protocol conformance. Catches interface mismatches at compile time. |
| **Pytest** | Testing | Standard Python test framework. `pytest-asyncio` for async tests. `pytest-cov` for coverage. |
| **testcontainers** | Integration testing | PostgreSQL and Redis in throwaway Docker containers. No mocking needed for database tests. |
| **GitHub Actions** | CI/CD | Lint → Test → Build → Deploy pipeline. Matrix testing across Python versions. Docker build and push. |

### 4.4 Configuration Management

All configuration uses **pydantic-settings** with environment variable loading:

```
Settings hierarchy:
  1. Environment variables (highest priority)
  2. .env file (local development)
  3. Default values in Pydantic models (lowest priority)
```

Configuration domains are separated into distinct models:
- `DatabaseSettings` — PostgreSQL connection, pool size
- `RedisSettings` — Redis connection
- `BrokerSettings` — PocketOption SSID, max subscriptions
- `TelegramSettings` — Bot token, allowed users, webhook config
- `StrategySettings` — Per-strategy parameters loaded from YAML
- `LoggingSettings` — Log level, format, output

### 4.5 Logging, Metrics, and Monitoring

#### Logging

**structlog** over loguru or stdlib logging.

Rationale:
- Structured JSON output by default (parsable by Loki, Elasticsearch).
- Context variable binding (`structlog.contextvars`) works correctly with asyncio.
- Processor pipeline architecture is extensible without subclassing.
- `filter_callable` for dynamic log level changes.
- Production-proven at scale.

Output format (development): Colored console with timestamps.
Output format (production): JSON to stdout, collected by Vector/Filebeat.

#### Metrics

**prometheus_client** for application metrics.

Key metrics:
- `signals_generated_total{symbol,strategy}` — Counter
- `trades_executed_total{symbol,result}` — Counter
- `signal_computation_seconds{symbol}` — Histogram
- `broker_connection_status` — Gauge (0/1)
- `active_strategies` — Gauge
- `queue_depth{queue_name}` — Gauge

Prometheus endpoint exposed at `/metrics` via FastAPI.

**Not using OpenTelemetry initially.** The tracing overhead doesn't justify the benefit for a single-process application. Add OpenTelemetry if/when the system becomes distributed across multiple services.

#### Health Checks

- `/health` — Liveness: process alive, DB connected, Redis connected.
- `/ready` — Readiness: data pipelines loaded, caches warm, strategies initialized.

---

## 5. Recommended System Architecture

### 5.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            INTERFACES LAYER                              │
│                                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │   Telegram   │  │    REST     │  │  Dashboard   │  │     Mobile    │  │
│  │     Bot      │  │  (FastAPI)  │  │  (Future)    │  │   (Future)    │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └───────┬───────┘  │
│         │                │                │                  │          │
│  ┌──────┴────────────────┴────────────────┴──────────────────┴───────┐  │
│  │                     APPLICATION LAYER                               │  │
│  │                                                                     │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │  │
│  │  │ SignalUseCase │  │StrategyUseCase│  │BacktestUseCase│           │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘            │  │
│  │         │                 │                 │                      │  │
│  │  ┌──────┴─────────────────┴─────────────────┴───────────────────┐  │  │
│  │  │                     DOMAIN LAYER                              │  │
│  │  │                                                               │  │
│  │  │  ┌──────────┐  ┌───────────┐  ┌────────────┐  ┌───────────┐  │  │
│  │  │  │ Signal   │  │  Strategy  │  │  Trade     │  │ FeatureSet│  │  │
│  │  │  │ Entity   │  │  Aggregate │  │  Entity    │  │  VO       │  │  │
│  │  │  └──────────┘  └───────────┘  └────────────┘  └───────────┘  │  │
│  │  │                                                               │  │
│  │  │  ┌──────────────────────────────────────────────────────────┐  │  │
│  │  │  │              Domain Events                                │  │  │
│  │  │  │  SignalGenerated  TradeOpened  TradeExpired  BalanceChanged│  │  │
│  │  │  └──────────────────────────────────────────────────────────┘  │  │
│  │  │                                                               │  │
│  │  │  ┌──────────────────────────────────────────────────────────┐  │  │
│  │  │  │              Ports (Protocols)                            │  │  │
│  │  │  │  BrokerPort  SignalRepository  StrategyRepository         │  │  │
│  │  │  │  EventBus  Clock  FeatureStore                            │  │  │
│  │  │  └──────────────────────────────────────────────────────────┘  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    INFRASTRUCTURE LAYER                           │  │
│  │                                                                   │  │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐  │  │
│  │  │ MessageBus     │  │ RepositoryImpl │  │ BrokerAdapter      │  │  │
│  │  │ (Redis pub/sub)│  │ (PostgreSQL)   │  │ (BinaryOptionsTools)│  │  │
│  │  └────────────────┘  └────────────────┘  └────────────────────┘  │  │
│  │                                                                   │  │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐  │  │
│  │  │ DataCatalog    │  │ FeatureEngine  │  │ MlflowClient       │  │  │
│  │  │ (DuckDB+Parquet)│  │ (pandas-ta)   │  │ (model registry)   │  │  │
│  │  └────────────────┘  └────────────────┘  └────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Component Architecture

#### Signal Pipeline (Core Processing Component)

```
Raw Candle → Feature Extraction → Signal Generation → Confidence Scoring → Signal
     │              │                    │                      │              │
     │         FeatureStore          ML Model            Calibration         │
     │         (pandas-ta)          (XGBoost)             (Platt)            │
     │                               Optuna                                  │
     │                              params                                   │
```

Each stage is a pluggable component. Stages communicate via typed events. New feature extractors, models, and calibration methods can be added without changing other stages.

#### Strategy Component

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│  Signal   │────▶│   Risk       │────▶│   Trade      │────▶│   Trade    │
│  Pipeline │     │   Manager    │     │   Executor   │     │   Logger   │
└──────────┘     └──────────────┘     └──────────────┘     └────────────┘
                       │
                       ▼
                ┌──────────────┐
                │  Protection   │
                │  (circuit     │
                │   breakers)   │
                └──────────────┘
```

- **Risk Manager**: Applies position sizing, max drawdown limits, cooldown periods.
- **Trade Executor**: Calls broker adapter to place trades. Implements retry with idempotency.
- **Protection**: Circuit breakers that pause trading when predefined thresholds are breached.
- **Trade Logger**: Persists every trade with full context (signal ID, strategy, timestamp, result).

#### Orchestrator

The Orchestrator manages the overall system lifecycle:

```
┌──────────────────────────────────────────────┐
│              Orchestrator                     │
│                                               │
│  1. Load configuration                        │
│  2. Initialize infrastructure (DB, Redis)     │
│  3. Connect to broker (BinaryOptionsTools-v2) │
│  4. Initialize strategy pipeline              │
│  5. Subscribe to market data                  │
│  6. Start signal generation loop              │
│  7. Monitor health and connections            │
│  8. Handle shutdown gracefully                │
└──────────────────────────────────────────────┘
```

### 5.3 Layered Architecture

```
Layer               Depends On                    Contains
─────               ──────────                    ────────
interfaces/         application, domain           Telegram bot, FastAPI routes, CLI
application/        domain                        Use cases, DTOs, ports
domain/             nothing                       Entities, value objects, aggregates,
                                                  events, repository protocols
infrastructure/     domain (protocols)            PostgreSQL repos, Redis cache,
                                                  BinaryOptionsTools-v2 adapter,
                                                  MLflow client, DuckDB catalog
```

**Dependency rule:** Source code dependencies must point only inward. Nothing in the domain layer can depend on anything in the application, infrastructure, or interfaces layers.

**What this means in practice:**
- Domain entities (`Signal`, `Trade`, `Strategy`) import nothing but Pydantic.
- Application use cases (`GetSignal`, `ExecuteTrade`) depend on domain entities and ports only.
- Infrastructure adapters (`PostgresSignalRepository`, `PocketOptionBrokerAdapter`) implement domain ports.
- Interface adapters (`TelegramSignalHandler`, `FastAPISignalController`) call application use cases.

### 5.4 Folder Structure

```
trade/
├── pyproject.toml                  # Project metadata, dependencies, tool config
├── uv.lock                         # Lockfile (committed)
├── Dockerfile                      # Multi-stage production build
├── docker-compose.yml              # Local development environment
├── .env.example                    # Template for environment variables
│
├── domain/                         # PURE PYTHON — zero infrastructure imports
│   ├── __init__.py
│   ├── entities/
│   │   ├── signal.py               # Signal entity
│   │   ├── trade.py                # Trade entity (binary option)
│   │   ├── strategy.py             # Strategy aggregate root
│   │   └── subscription.py        # User subscription entity
│   ├── value_objects/
│   │   ├── symbol.py               # Typed symbol (validated)
│   │   ├── money.py                # Decimal-based monetary value
│   │   ├── timeframe.py            # Candle timeframe (1s, 60s, 300s)
│   │   ├── direction.py            # CALL/PUT enum
│   │   └── confidence.py           # Normalized confidence score [0,1]
│   ├── events/
│   │   ├── signal_generated.py     # New signal produced
│   │   ├── trade_opened.py         # Trade placed
│   │   ├── trade_expired.py        # Option expired
│   │   ├── trade_result.py         # Win/loss/draw determined
│   │   └── balance_changed.py      # Account balance updated
│   ├── services/
│   │   ├── signal_evaluator.py     # Domain logic for signal evaluation
│   │   └── risk_calculator.py      # Position sizing logic
│   └── ports/
│       ├── broker.py               # BrokerPort protocol
│       ├── repositories.py         # SignalRepository, TradeRepository, etc.
│       ├── event_bus.py            # EventBus protocol
│       ├── clock.py                # Clock protocol (for testability)
│       └── feature_store.py        # FeatureStore protocol
│
├── application/
│   ├── __init__.py
│   ├── use_cases/
│   │   ├── generate_signal.py      # GenerateSignal use case
│   │   ├── execute_trade.py        # ExecuteTrade use case
│   │   ├── get_signal_history.py   # GetSignalHistory use case
│   │   ├── manage_strategy.py      # Create/Update/Delete strategy
│   │   ├── run_backtest.py         # RunBacktest use case
│   │   └── manage_subscription.py  # User subscription management
│   ├── ports/
│   │   ├── telegram_bot.py         # TelegramBotPort (for sending notifications)
│   │   └── signal_presenter.py     # SignalPresenter protocol
│   └── dto/
│       ├── signal_dto.py           # Signal data transfer objects
│       ├── trade_dto.py
│       └── backtest_dto.py
│
├── infrastructure/
│   ├── __init__.py
│   ├── broker/
│   │   ├── __init__.py
│   │   ├── broker_adapter.py       # BrokerPort implementation via BinaryOptionsTools-v2
│   │   ├── virtual_market.py       # Extended virtual market with spread/slippage
│   │   └── backtest_broker.py      # Deterministic broker for backtesting
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── postgres/
│   │   │   ├── connection.py       # PostgreSQL connection management
│   │   │   ├── repositories.py     # All repository implementations
│   │   │   └── migrations/         # Alembic migration scripts
│   │   ├── duckdb/
│   │   │   ├── catalog.py          # DuckDB DataCatalog implementation
│   │   │   └── queries.py          # Analytical queries
│   │   └── redis/
│   │       ├── cache.py            # Redis cache adapters
│   │       ├── pubsub.py           # Redis pub/sub for real-time events
│   │       └── rate_limiter.py     # Token bucket rate limiter
│   ├── ml/
│   │   ├── __init__.py
│   │   ├── model_service.py        # Model loading, inference, versioning
│   │   ├── mlflow_client.py        # MLflow tracking and registry client
│   │   └── training_pipeline.py    # Full training pipeline (features → model)
│   ├── features/
│   │   ├── __init__.py
│   │   ├── feature_pipeline.py     # Feature extraction pipeline
│   │   ├── indicators/
│   │   │   ├── rsi.py              # RSI feature
│   │   │   ├── macd.py             # MACD feature
│   │   │   ├── bollinger.py        # Bollinger Bands feature
│   │   │   └── custom.py           # Custom indicator framework
│   │   └── store.py                # Feature store (Parquet-based)
│   ├── research/
│   │   ├── __init__.py
│   │   ├── data_catalog.py         # DataCatalog: unified historical data access
│   │   ├── backtest_engine.py      # Vectorized backtesting engine
│   │   ├── walk_forward.py         # Walk-forward validation
│   │   └── optimizer.py            # Optuna-based hyperparameter optimization
│   ├── event_bus.py                # In-process event bus implementation
│   └── clock.py                    # System clock implementation
│
├── interfaces/
│   ├── __init__.py
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bot.py                  # Application assembly, DI wiring
│   │   ├── config.py               # Telegram-specific settings
│   │   ├── main.py                 # Entry point for standalone service
│   │   ├── handlers/
│   │   │   ├── base.py             # Base handler (auth, rate limit)
│   │   │   ├── start.py            # /start, /help
│   │   │   ├── signals.py          # /signal, /subscribe, /unsubscribe
│   │   │   ├── portfolio.py        # /portfolio, /stats
│   │   │   └── admin.py            # /admin broadcast, stats
│   │   └── presentation/
│   │       ├── formatters.py       # Signal → Telegram message
│   │       └── menus.py            # Inline keyboard builders
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI application creation
│   │   ├── deps.py                 # Dependency injection for routes
│   │   ├── middleware.py           # CORS, logging, metrics
│   │   ├── v1/
│   │   │   ├── signals.py          # GET/POST /v1/signals
│   │   │   ├── trades.py           # GET /v1/trades
│   │   │   ├── strategies.py       # CRUD /v1/strategies
│   │   │   ├── backtests.py        # POST /v1/backtests
│   │   │   └── admin.py            # GET /v1/admin/health
│   │   └── ws/
│   │       └── market_data.py      # WebSocket /ws/{symbol}
│   └── cli/
│       ├── __init__.py
│       └── commands.py             # CLI commands for admin, research, backtest
│
├── engine/                          # Core orchestration
│   ├── __init__.py
│   ├── orchestrator.py             # System lifecycle manager
│   ├── signal_pipeline.py          # Signal generation pipeline coordinator
│   ├── trade_executor.py           # Trade execution coordinator
│   └── pipeline_context.py         # Shared context for pipeline stages
│
├── config/
│   ├── __init__.py
│   ├── settings.py                 # Pydantic-settings main model
│   ├── strategies/                 # YAML strategy configuration files
│   │   ├── momentum.yaml
│   │   └── mean_reversion.yaml
│   └── logging.py                  # structlog configuration
│
├── scripts/
│   ├── download_data.py            # Historical data download tool
│   ├── train_model.py              # Model training script
│   └── export_features.py          # Feature export pipeline
│
├── storage/
│   ├── parquet/                    # Historical market data (Parquet files)
│   ├── models/                     # Trained model artifacts
│   └── experiments/                # MLflow experiment data
│
├── research/
│   ├── notebooks/                  # Jupyter notebooks
│   ├── backtests/                  # Backtest configurations and results
│   ├── walk_forward/               # Walk-forward validation outputs
│   └── reports/                    # Generated analysis reports
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures (testcontainers, etc.)
│   ├── domain/                     # Domain entity tests
│   ├── application/                # Use case tests
│   ├── infrastructure/             # Adapter tests (integration)
│   ├── interfaces/                 # API and Telegram tests
│   └── engine/                     # Pipeline integration tests
│
└── docs/
    ├── architecture/               # Architecture documentation
    ├── adr/                        # Architecture Decision Records
    └── api/                        # API documentation
```

### 5.5 Dependency Graph

```
domain         → (none)
application    → domain
infrastructure → domain (protocols only)
interfaces     → application, domain
engine         → application, domain, infrastructure
config         → (none) — consumed by all
tests          → domain, application, infrastructure, interfaces, engine
```

### 5.6 Communication Flow

```
In-process communication:  Event Bus (type-routed, async)
Cross-process:             Redis pub/sub
Cross-service:             REST API / WebSocket
```

**Event flow for signal generation:**

```
1. BrokerAdapter receives candle via BinaryOptionsTools-v2 WebSocket
2. BrokerAdapter publishes CandleReceived event on in-process event bus
3. SignalPipeline subscribes to CandleReceived
4. SignalPipeline computes features (indicators)
5. SignalPipeline loads ML model from MLflow registry
6. SignalPipeline generates prediction + confidence score
7. SignalPipeline publishes SignalGenerated event
8. RiskManager subscribes to SignalGenerated:
     a. Applies position sizing
     b. Checks circuit breakers
     c. If approved, publishes TradeApproved event
9. TradeExecutor subscribes to TradeApproved:
     a. Calls BrokerAdapter.place_trade()
     b. Publishes TradeOpened event
10. TradeLogger subscribes to TradeOpened → persists to PostgreSQL
11. TelegramInterface subscribes to TradeOpened → formats and sends notification
```

All subscribers are independent. Any can be removed, replaced, or tested in isolation.

---

## 6. Domain Design

### 6.1 Core Domains and Bounded Contexts

```
┌─────────────────────────────────────────────────────────────┐
│                   BOUNDED CONTEXTS                            │
├─────────────────┬─────────────────┬─────────────────────────┤
│   RESEARCH      │   TRADING        │   USER & SUBSCRIPTION   │
├─────────────────┼─────────────────┼─────────────────────────┤
│ Features        │ Signal Gen       │ User management         │
│ Indicators      │ Trade Execution  │ Authentication          │
│ Backtesting     │ Risk Management  │ Subscription plans      │
│ Walk-forward    │ Position Sizing  │ API keys                │
│ Hyperopt        │ Trade Logging    │ Rate limits             │
│ ML Training     │ PnL Tracking     │ Preferences             │
│ Data Catalog    │ Broker Comm      │                         │
├─────────────────┼─────────────────┼─────────────────────────┤
│   MONITORING    │   CONFIGURATION  │   NOTIFICATION           │
├─────────────────┼─────────────────┼─────────────────────────┤
│ Health checks   │ Strategy Config  │ Telegram delivery        │
│ Metrics         │ System Settings  │ Email (future)           │
│ Alerts          │ Feature Flags   │ Web push (future)        │
│ Audit Log       │ User Config     │ In-app (future)          │
└─────────────────┴─────────────────┴─────────────────────────┘
```

### 6.2 Core Domain Entities

#### Signal

```
Signal {
    id: UUID
    symbol: Symbol
    direction: Direction (CALL | PUT)
    confidence: Confidence (0.0 - 1.0)
    strategy_id: UUID
    features: dict[str, float]       # Feature values at signal time
    model_version: str               # ML model version
    candle_timestamp: datetime       # Candle that triggered signal
    generated_at: datetime           # When signal was produced
    metadata: dict[str, Any]         # Extensible
}
```

#### Trade (Binary Option)

```
Trade {
    id: UUID
    signal_id: UUID                  # Link to originating signal
    strategy_id: UUID
    symbol: Symbol
    direction: Direction
    amount: Money
    timeframe: Timeframe             # Option duration in seconds
    status: TradeStatus (PENDING | OPEN | EXPIRED | SETTLED)
    entry_price: Decimal
    exit_price: Decimal | None
    result: TradeResult (WIN | LOSS | DRAW) | None
    payout: Decimal                  # Payout percentage
    profit_loss: Money | None
    broker_trade_id: str             # PocketOption trade ID
    opened_at: datetime
    expires_at: datetime
    settled_at: datetime | None
    metadata: dict[str, Any]
}
```

#### Strategy Aggregate

```
Strategy {
    id: UUID
    name: str
    version: str
    status: StrategyStatus (DRAFT | ACTIVE | PAUSED | ARCHIVED)
    
    // Configuration
    symbols: list[Symbol]
    timeframe: Timeframe
    max_position_size: Money
    max_daily_trades: int
    cooldown_minutes: int
    risk_per_trade: Decimal (0.0 - 1.0)
    
    // ML Configuration
    model_uri: str                    # MLflow model URI
    feature_config: FeatureConfig     # Which features to compute
    
    // Performance (updated by system)
    total_trades: int
    wins: int
    losses: int
    current_streak: int
    total_pnl: Money
    sharpe_ratio: Decimal | None
    last_updated: datetime
    
    // Domain methods
    def should_trade(self, signal: Signal) -> bool: ...
    def calculate_position_size(self, balance: Money) -> Money: ...
    def update_performance(self, trade: Trade): ...
}
```

### 6.3 Key Value Objects

```
Symbol(code: str, broker_name: str)         # "EURUSD_otc" on PocketOption
Money(amount: Decimal, currency: str)       # Immutable, arithmetic operations
Timeframe(seconds: int)                     # 60, 300 — validated
Direction(CALL | PUT)                       # Enum
Confidence(score: float)                    # [0.0, 1.0], validated
TradeStatus(PENDING | OPEN | EXPIRED | SETTLED)  # Enum
TradeResult(WIN | LOSS | DRAW)              # Enum
FeatureConfig(features: list[FeatureDef])   # Which indicators to compute
FeatureDef(name: str, params: dict)         # "rsi", {"window": 14}
```

### 6.4 Domain Events

```
SignalGenerated(
    signal_id: UUID, strategy_id: UUID, symbol: Symbol,
    direction: Direction, confidence: Confidence,
    feature_values: dict[str, float], candle_timestamp: datetime
)

TradeOpened(
    trade_id: UUID, signal_id: UUID, strategy_id: UUID,
    symbol: Symbol, direction: Direction, amount: Money,
    entry_price: Decimal, expires_at: datetime
)

TradeExpired(
    trade_id: UUID, outcome: TradeResult, profit_loss: Money
)

TradeResult(
    trade_id: UUID, result: TradeResult,
    profit_loss: Money, entry_price: Decimal, exit_price: Decimal
)

BalanceChanged(new_balance: Money, old_balance: Money)

BrokerDisconnected(reconnect_attempt: int, next_attempt_in: float)

BrokerReconnected(attempts: int)

StrategyError(strategy_id: UUID, error: str, context: dict)
```

### 6.5 Repository Ports (Protocols)

```python
class SignalRepository(Protocol):
    async def save(self, signal: Signal) -> None: ...
    async def get(self, id: UUID) -> Signal | None: ...
    async def get_by_strategy(self, strategy_id: UUID, limit: int = 100) -> list[Signal]: ...
    async def get_by_symbol(self, symbol: Symbol, since: datetime, limit: int) -> list[Signal]: ...
    async def get_latest(self, symbol: Symbol) -> Signal | None: ...

class TradeRepository(Protocol):
    async def save(self, trade: Trade) -> None: ...
    async def get(self, id: UUID) -> Trade | None: ...
    async def get_by_strategy(self, strategy_id: UUID, limit: int = 100) -> list[Trade]: ...
    async def get_by_symbol(self, symbol: Symbol, since: datetime) -> list[Trade]: ...
    async def get_pending(self) -> list[Trade]: ...
    async def get_open(self) -> list[Trade]: ...
    async def update_result(self, id: UUID, result: TradeResult, pnl: Money, exit_price: Decimal) -> None: ...

class StrategyRepository(Protocol):
    async def save(self, strategy: Strategy) -> None: ...
    async def get(self, id: UUID) -> Strategy | None: ...
    async def get_active(self) -> list[Strategy]: ...
    async def delete(self, id: UUID) -> None: ...

class EventStore(Protocol):
    async def append(self, event: BaseModel) -> None: ...
    async def get_by_aggregate(self, aggregate_id: UUID, aggregate_type: str) -> list[BaseModel]: ...
    async def get_by_type(self, event_type: type, since: datetime) -> list[BaseModel]: ...
```

### 6.6 Broker Port

```python
class BrokerPort(Protocol):
    """Abstract interface for binary options broker communication."""
    
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def is_connected(self) -> bool: ...
    
    async def get_balance(self) -> Money: ...
    async def get_assets(self) -> list[AssetInfo]: ...
    async def get_payout(self, symbol: Symbol) -> int: ...
    
    async def place_option(self, symbol: Symbol, amount: Money,
                           direction: Direction, timeframe: Timeframe) -> Trade: ...
    async def get_trade_result(self, trade_id: str) -> TradeResult: ...
    
    def subscribe_candles(self, symbol: Symbol, timeframe: Timeframe) -> AsyncIterator[Candle]: ...
    def subscribe_ticks(self, symbol: Symbol) -> AsyncIterator[Tick]: ...
    
    async def get_candles(self, symbol: Symbol, timeframe: Timeframe,
                          count: int) -> list[Candle]: ...
    async def compile_candles(self, symbol: Symbol, timeframe: Timeframe,
                              lookback: int) -> list[Candle]: ...
    
    @property
    def on_disconnect(self) -> AsyncIterator[DisconnectEvent]: ...
```

### 6.7 Service Boundaries

Service boundaries follow domain aggregates:

| Service | Owns | Communicates via |
|---------|------|-----------------|
| SignalService | Signal | Events |
| TradingService | Trade, Strategy | Events + Repository |
| RiskService | Risk rules | Events (reads signals, writes risk decisions) |
| BacktestService | Backtest runs | Direct (orchestrates inside process) |
| ResearchService | Features, Models | Direct (research scripts) |
| UserService | Users, Subscriptions | REST API |
| NotificationService | Outbound messages | Events |

---

## 7. Data Flow

### 7.1 Historical Research Flow

```
User Research Request
    │
    ▼
ResearchService
    │
    ├── 1. Check DataCatalog for cached data
    │       ├── Cache HIT → Load from DuckDB/Parquet
    │       └── Cache MISS → Download from:
    │               ├── Broker API (BinaryOptionsTools-v2 historical candles)
    │               ├── Dukascopy (local files)
    │               └── Alpha Vantage / Twelve Data (supplementary)
    │
    ├── 2. Store raw data to Parquet (versioned via DVC)
    │
    ├── 3. FeaturePipeline.compute():
    │       ├── Load raw OHLCV
    │       ├── Compute indicators (pandas-ta)
    │       ├── Compute custom features (numba/numpy)
    │       ├── Lag features (shift(1) to prevent look-ahead)
    │       └── Store feature matrix to Parquet
    │
    ├── 4. [Optional] TrainingPipeline:
    │       ├── Load feature matrix
    │       ├── Train/test split (time-series aware)
    │       ├── Train XGBoost/LightGBM model
    │       ├── Log to MLflow (params, metrics, artifacts)
    │       └── Register model in MLflow Model Registry
    │
    └── 5. Return FeatureSet / Model to caller
```

### 7.2 Live WebSocket Flow

```
PocketOption Server
    │
    ▼ (WebSocket Socket.IO)
BinaryOptionsTools-v2 (Rust core)
    │
    ├── 1. Message received via tokio-tungstenite
    ├── 2. Router dispatches to subscription module
    ├── 3. Candle produced from aggregation engine
    └── 4. StreamIterator yields candle to Python
            │
            ▼
BrokerAdapter (infrastructure/broker/)
    │
    ├── 5. Parse JSON candle → Candle domain object
    ├── 6. Publish CandleReceived event on EventBus
    │       │
    │       ▼
    │   Subscribers (all async, non-blocking):
    │       ├── SignalPipeline: compute → generate signal
    │       ├── DataLogger: persist candle to PostgreSQL
    │       ├── MetricsCollector: update prometheus metrics
    │       └── WebSocketBroadcaster: push to dashboard/API clients
    │
    └── 7. Handle connection state changes:
            ├── On disconnect: publish BrokerDisconnected
            └── On reconnect: publish BrokerReconnected
```

### 7.3 Signal Generation Flow

```
CandleReceived event
    │
    ▼
SignalPipeline (engine/signal_pipeline.py)
    │
    ├── 1. Load Strategy from StrategyRepository
    │
    ├── 2. FeatureEngine.compute(strategy.feature_config, candle):
    │       ├── For each FeatureDef in config:
    │       │       ├── Load required history from feature store
    │       │       └── Compute indicator value
    │       └── Return feature vector (dict[str, float])
    │
    ├── 3. ModelService.predict(feature_vector, strategy.model_uri):
    │       ├── Load model from MLflow registry (cached)
    │       ├── Transform features (same scaler as training)
    │       └── Run inference → prediction + confidence
    │
    ├── 4. Create Signal entity
    │       ├── direction = CALL if prediction > threshold
    │       ├── confidence = calibrated confidence score
    │       ├── features = feature vector snapshot
    │       └── model_version = loaded model version
    │
    ├── 5. Save signal to SignalRepository
    │
    ├── 6. Publish SignalGenerated event
    │
    └── 7. [Async] RiskManager handles SignalGenerated:
            ├── strategy.should_trade(signal)?
            │   ├── YES → strategy.calculate_position_size(balance)
            │   │       └── Publish TradeApproved(signal, position_size)
            │   └── NO → discard signal
            │
            ▼
        TradeExecutor handles TradeApproved:
            ├── Call BrokerAdapter.place_option(...)
            ├── On success: save Trade, publish TradeOpened
            └── On failure: log error, publish TradeFailed
```

### 7.4 Telegram Flow

```
User sends /signal EURUSD_otc
    │
    ▼
Telegram Handler (interfaces/telegram/handlers/signals.py)
    ├── 1. Extract user_id from update.effective_user.id
    ├── 2. Check authorization (user_id in ALLOWED_USER_IDS)
    ├── 3. Check rate limit (token bucket, Redis-backed)
    ├── 4. Parse command arguments (symbol, optional timeframe)
    │
    ▼
GenerateSignal use case (application/use_cases/generate_signal.py)
    ├── 1. Validate symbol via Symbol value object
    ├── 2. Get latest candle from BrokerAdapter
    ├── 3. Compute features via FeatureEngine
    ├── 4. Get signal from ModelService
    ├── 5. Save to SignalRepository
    └── 6. Return Signal DTO
    │
    ▼
Telegram Handler (back in interface layer)
    ├── 1. Call SignalFormatter.format(signal) → Telegram message
    ├── 2. Call update.message.reply_text(formatted, parse_mode="MarkdownV2")
    └── 3. (Optional) Send signal notification to subscribers
```

**Key constraint:** The Telegram handler contains zero business logic. It:
- Parses Telegram-specific constructs (commands, callback queries)
- Calls application use cases
- Formats results into Telegram messages

### 7.5 Backtesting Flow

```
User initiates backtest (via CLI, API, or Telegram)
    │
    ▼
RunBacktest use case (application/use_cases/run_backtest.py)
    │
    ├── 1. Load strategy configuration
    ├── 2. Load historical data from DataCatalog
    │       ├── DuckDB for fast range queries
    │       └── Parquet files for raw storage
    │
    ├── 3. [Vectorized Phase] Fast research backtest:
    │       ├── Compute all indicators at once (pandas-ta / numpy)
    │       ├── Generate signal series
    │       ├── Simulate trade outcomes
    │       ├── Compute performance metrics
    │       └── Log to MLflow
    │
    ├── 4. [Event-Driven Phase] Realistic validation:
    │       ├── For each candle in chronological order:
    │       │       ├── Compute features (same code as live)
    │       │       ├── Generate signal
    │       │       ├── Execute via VirtualMarket (with spread/slippage)
    │       │       └── Record trade
    │       ├── Compare results with vectorized phase
    │       └── Report discrepancies (indicator implementation differences)
    │
    └── 5. Return BacktestResult with:
            ├── Performance metrics (Sharro, Sortino, max DD, win rate, CAGR)
            ├── Trade list (full details)
            ├── Equity curve
            ├── Statistical validation (DSR, PBO)
            └── Comparison vs benchmark
```

**Why two-phase backtesting:**
- Vectorized phase enables rapid parameter sweeps and idea validation (seconds, not minutes).
- Event-driven phase validates against the exact code path used in production (eliminates vectorized/event-driven divergence risk).
- Both phases must converge before a strategy is considered validated.

### 7.6 Deployment Flow

```
Build Stage (GitHub Actions)
    ├── uv lock --check         (lockfile integrity)
    ├── ruff check .            (lint)
    ├── mypy src/               (type check)
    ├── pytest tests/unit       (unit tests)
    ├── pytest tests/integration --with-db --with-redis  (integration tests)
    └── Docker build --target production  (multi-stage build)
    │
Release Stage
    ├── Push Docker image to registry (ghcr.io)
    └── Tag version (semver)
    │
Deploy Stage
    ├── docker compose -f docker-compose.prod.yml pull
    ├── docker compose -f docker-compose.prod.yml up -d
    └── Health check: /health → 200
```

---

## 8. Engineering Principles

### 8.1 Coding Philosophy

| Principle | Rule | Rationale |
|-----------|------|-----------|
| **Type safety** | Every function has typed parameters and return types. `mypy --strict` enforces it. | Catches interface mismatches at CI time. Documents intent without comments. |
| **No placeholder implementations** | Don't commit `pass`, `TODO`, or `NotImplementedError`. Implement or don't merge. | Avoids accumulating technical debt disguised as "future work." |
| **Test before merge** | Every feature ships with tests. Every bug fix adds a regression test. | Non-negotiable for financial software. Untested code is broken code. |
| **Pydantic everywhere** | All external data is validated at boundaries. Internal data is valid by construction. | Prevents garbage data from propagating. Self-documenting schemas. |
| **Composition over inheritance** | Prefer small, composable types over deep class hierarchies. | Easier to test, extend, and reason about individually. |
| **Modules under 400 lines** | If a module exceeds 400 lines, extract. | Prevents god classes. Encourages clean separation of concerns. |
| **No hidden magic** | No metaclasses, no dynamic imports, no monkey-patching. | Readability matters more than cleverness. Debugging opaque code is expensive. |

### 8.2 Architecture Philosophy

| Principle | Rule | Rationale |
|-----------|------|-----------|
| **Dependency inversion** | Domain defines the interfaces. Infrastructure implements them. | Keeps domain pure and testable. Infrastructure becomes replaceable. |
| **Event-driven coupling** | Components communicate via events, not direct calls (within reason). | Enables independent testing, replacement, and scaling of components. |
| **Explicit error channels** | Expected failures return `Result[T, Error]`. Unexpected failures raise exceptions. | Makes error handling visible in type signatures. Exceptions are for programmer mistakes, not business logic. |
| **Boundaries are explicit** | Layer boundaries are package boundaries. Importing across boundaries requires explicit dependency in `pyproject.toml`. | Prevents accidental coupling. Enforces architectural rules at build time. |
| **Configuration is code** | Every configuration value is validated by a Pydantic model. | Catches configuration errors at startup, not runtime. |
| **Reproducibility** | Every experiment is linked to a git commit, dataset version, and configuration. | Enables debugging "why did that strategy work last week but not today?" |

### 8.3 Dependency Rules

```
                    ┌──────────────────┐
                    │    interfaces/   │
                    │  Telegram / API  │
                    └────────┬─────────┘
                             │ depends on
                             ▼
                    ┌──────────────────┐
                    │  application/    │
                    │  (use cases)     │
                    └────────┬─────────┘
                             │ depends on
                             ▼
          ┌──────────────────────────────────┐
          │           domain/                │
          │  entities / events / ports       │
          │  (imports nothing external)      │
          └────────┬──────────┬──────────────┘
                   │          │
          depends on ports    │ depends on ports
                   ▼          ▼
          ┌──────────────────────────────┐
          │     infrastructure/          │
          │  adapters / implementations  │
          └──────────────────────────────┘
```

**Enforcement:**
- `domain/` cannot import from `application/`, `infrastructure/`, or `interfaces/`.
- `application/` cannot import from `infrastructure/` or `interfaces/`.
- `infrastructure/` can import from `domain/` (to implement ports).
- `interfaces/` can import from `application/` and `domain/`.

### 8.4 Error Handling

**Rule:** Expected failures use `Result[T, Error]`. Unexpected failures raise exceptions.

```python
# Expected: network failure, invalid symbol, rate limit
Result[Signal, SignalError]
Result[Trade, TradeError]

# Unexpected: programming error, data corruption
raise ValueError("Unexpected state: ...")   # Programmer mistake
```

**Error hierarchy:**
```
DomainError (base)
├── SignalError
│   ├── SignalGenerationError
│   └── SignalNotFoundError
├── TradeError
│   ├── TradeExecutionError
│   ├── TradeExpiryError
│   └── InsufficientBalanceError
├── StrategyError
│   ├── StrategyNotFoundError
│   └── StrategyConfigError
└── BrokerError
    ├── ConnectionError
    ├── AuthenticationError
    └── RateLimitError
```

### 8.5 Logging

```python
# Application layer — log decisions, not data
logger.info("signal.generated", strategy_id=strategy.id, symbol=symbol, direction=direction)

# Infrastructure layer — log technical details
logger.info("broker.candle.received", symbol=symbol, price=price, timestamp=ts)
logger.warning("broker.reconnecting", attempt=n, next_attempt=s)

# Error handling — structured context
logger.error("trade.execution.failed", trade_id=trade.id, error=str(exc), exc_info=exc)
```

**Log levels convention:**
- `ERROR`: System cannot proceed. Human intervention required.
- `WARNING`: Degraded but operational. Important for monitoring.
- `INFO`: Normal operations. Strategy started, trade placed, signal generated.
- `DEBUG`: Detailed flow for debugging. Feature values, timing breakdowns.

### 8.6 Configuration

```python
# config/settings.py
class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")
    
    debug: bool = False
    log_level: str = "INFO"
    
    db: PostgresConfig = PostgresConfig()
    redis: RedisConfig = RedisConfig()
    broker: BrokerConfig = BrokerConfig()
    telegram: TelegramConfig = TelegramConfig()
    strategy: StrategyConfig = StrategyConfig()

class PostgresConfig(BaseSettings):
    url: PostgresDsn = "postgresql://localhost:5432/trading"
    pool_min: int = 5
    pool_max: int = 20
    connect_timeout: int = 30
```

### 8.7 Testing

| Layer | Tool | What to Test | Mock Strategy |
|-------|------|-------------|---------------|
| **Domain** | pytest | Entity behavior, value object validation, domain events | No mocking — pure functions |
| **Application** | pytest + pytest-asyncio | Use case orchestration, port interaction | Mock ports via `unittest.mock` or test doubles |
| **Infrastructure** | pytest + testcontainers | Repository implementations, broker adapter | Real PostgreSQL/Redis containers. Mock broker via `TestingWrapper`. |
| **Interfaces** | pytest + httpx | API routes, Telegram handlers | Mock use cases. Test formatting and routing. |
| **Integration** | pytest + docker-compose | Full pipeline: broker → signal → trade → persistence | Real dependencies except actual broker connection (use VirtualMarket). |

### 8.8 Documentation

- **ADR**: Every significant architectural decision documented in `docs/adr/`.
- **README**: Root README with project overview, setup, and quick start.
- **API docs**: Auto-generated from FastAPI (OpenAPI/Swagger).
- **Architecture docs**: This document and any updates.
- **Code comments**: Explain WHY, not WHAT. Code should be self-documenting for WHAT.

---

## 9. Risk Analysis

### 9.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| BinaryOptionsTools-v2 API changes in breaking ways | Low | High | Pin exact version. Wrap behind adapter. Monitor upstream changes. |
| PocketOption broker API changes | Medium | High | Abstract broker behind `BrokerPort`. If broker changes protocol, only the adapter changes. |
| TA-Lib installation on Windows/Linux | Medium | Medium | Have pandas-ta as primary (no C deps). TA-Lib is optional acceleration. |
| PyO3 Rust compilation failures | Low | Medium | Use prebuilt wheels via PyPI. Maintain local wheels for target platforms. |
| SSID expiration / session loss | High | Medium | Implement session health monitoring. Notify user when session expires. Document refresh procedure. |

### 9.2 Architectural Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Over-engineering (too many layers for simple use cases) | Medium | Medium | Start with concrete implementations. Extract interfaces when second implementation is needed. Don't abstract prematurely. |
| Event bus becoming a bottleneck | Low | Medium | Use in-process event bus. Separate high-volume events (candles) from low-volume events (trades). Monitor queue depth. |
| Strategy execution loop in BinaryOptionsTools-v2 blocking our pipeline | Medium | High | Our strategy is a thin proxy. Heavy computation happens in separate tasks/processes. Use `asyncio.Queue` to decouple. |
| ML model version drift | High | Medium | Log all feature values at signal time. Monitor feature distributions. Retrain on schedule (daily/weekly). Champion/challenger deployment. |

### 9.3 Performance Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Real-time indicator computation too slow for 1-second candles | Low | Medium | Use numba for critical paths. Pre-compute where possible. Profile before optimizing. |
| PostgreSQL write throughput for tick data | Low | Low | We don't store ticks. Only candles, signals, trades at ~10-100 writes/second. PostgreSQL handles this easily. |
| Redis memory exhaustion from pub/sub buffers | Low | Low | Set `maxmemory` policy. Monitor queue sizes. Use bounded queues. |
| ML inference latency | Medium | Low | XGBoost inference is sub-millisecond. Cache model in memory. Use ONNX runtime if needed. |

### 9.4 Security Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| SSID token exposure | Low | Critical | Never log SSIDs. Store in environment variables. Use Docker secrets in production. |
| Telegram bot compromise | Low | Medium | Limited to allowed users (whitelist). Bot can only read signals, not access broker or funds. |
| API authentication bypass | Low | High | JWT tokens for API access. Rate limiting per token. Audit logging of all auth attempts. |
| Dependency supply chain | Low | Medium | Pin dependencies with hash verification. Dependabot alerts. Regular `uv lock --check`. |

### 9.5 Maintenance Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Single maintainer knowledge bottleneck | High | High | Document architecture decisions (ADR). Write tests that capture intent. Use static typing for documentation. Review process for all changes. |
| pandas-ta discontinuation | Low | Medium | Custom indicators use numba, not pandas-ta. Migration requires reimplementing indicator calls, not the framework. |
| Python version upgrade | Low | Low | Pin Python version in Docker. Test against new Python before upgrading. |
| MLflow version changes | Low | Low | MLflow has stable API. Pin major version. Containerized deployment isolates from host changes. |

### 9.6 Scalability Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Single account limitation (one SSID) | Medium | Medium | Our architecture supports multiple broker instances. Future: one instance per account, unified via application layer. |
| Multiple users on same Telegram bot | Low | Low | Telegram user whitelisting. Per-user rate limits. Per-user strategy configuration. |
| Horizontal scaling of signal generation | Low | Low | Signal pipeline is stateless. Run multiple instances behind Redis pub/sub for event distribution. |

---

## 10. Open Questions

These questions must be answered before implementation begins. **Do not guess — verify with stakeholders.**

### 10.1 Business Domain

1. **Is the platform for personal use only, or will it be commercial?** License implications for BinaryOptionsTools-v2 (personal use license). Affects whether we need broker-neutral architecture or can focus on PocketOption exclusively.

2. **What is the acceptable latency for signal delivery?** From candle arrival to Telegram notification. Determines whether in-process event bus is sufficient or we need zero-copy paths.

3. **How many simultaneous strategies should the platform support?** Affects thread/process model and resource planning.

4. **What is the target number of symbols to monitor simultaneously?** BinaryOptionsTools-v2 has a default max subscription limit of 4. Can this be increased? Do we need multiple client instances?

5. **Is walk-forward validation required from day one, or can it follow in a later phase?** Affects research pipeline priority.

6. **What is the expected data retention requirement?** How long must historical trades, signals, and raw data be kept? Affects PostgreSQL partitioning strategy and storage planning.

### 10.2 Technical Domain

7. **Should BinaryOptionsTools-v2's license be verified before proceeding?** The repository states "Personal Use Only." If this is a commercial project, we need to contact the maintainers or find alternatives.

8. **Is the SSID acquisition process documented and reliable?** The user must extract an SSID from browser cookies. How do we handle SSID rotation/login requirements?

9. **What is the actual subscription limit for PocketOption?** The library defaults to 4 maximum subscriptions. Is this a broker limit or library implementation choice? Can it be increased?

10. **What is the PocketOption API compatibility guarantee?** Does the broker version the Socket.IO API? How frequently does it change?

### 10.3 Operational Domain

11. **What infrastructure is available?** Cloud (AWS/GCP/Azure), VPS, or local machine? Determines deployment architecture.

12. **Who manages the PostgreSQL and Redis instances?** DevOps support, or self-managed in Docker?

13. **Is there a monitoring/alerting system already in place?** Or do we need to set up Grafana, Prometheus, etc. from scratch?

14. **What is the expected uptime requirement?** 24/7 trading or session-based? Affects reconnection strategy and deployment approach.

### 10.4 ML Domain

15. **Is there existing historical data for model training?** Or do we need to collect data before ML strategies are viable?

16. **What is the expected retraining cadence?** Daily, weekly, monthly? Affects whether we need automated retraining pipelines from day one.

17. **Are we starting with ML strategies or rule-based strategies first?** ML introduces complexity (data collection, training, validation, monitoring). Rule-based can be operational much sooner.

---

## 11. Final Recommendations

### 11.1 How I Would Build This Platform

If I were the Principal Engineer responsible for maintaining this platform for the next five years, here is exactly how I would proceed:

#### Phase 0: Foundation (Weeks 1-4)

**Do not write any ML code yet. Do not build the Telegram bot yet.**

1. **Set up the project structure** exactly as described in Section 5.4.
2. **Configure `uv`** with `pyproject.toml` and workspace structure.
3. **Set up Docker Compose** with PostgreSQL 16 and Redis 7 for local development.
4. **Implement the domain layer first:**
   - All value objects (`Symbol`, `Money`, `Timeframe`, `Direction`, `Confidence`)
   - Core entities (`Signal`, `Trade`, `Strategy`)
   - Domain events (`SignalGenerated`, `TradeOpened`, `TradeExpired`, `TradeResult`)
   - Repository ports (`SignalRepository`, `TradeRepository`, `StrategyRepository`)
   - Broker port (`BrokerPort`)
   - Event bus protocol
5. **Write domain tests.** These are pure Python, fast, and validate all business logic.
6. **Set up CI** (GitHub Actions) with lint, type check, and test stages.

The goal of Phase 0 is a verified, tested domain model that everyone agrees on before any infrastructure choices are locked in.

#### Phase 1: Broker Integration (Weeks 3-6)

1. **Implement `PocketOptionBrokerAdapter`** wrapping BinaryOptionsTools-v2.
2. **Implement `VirtualMarket`** (extend BinaryOptionsTools-v2's version with spread/slippage).
3. **Write integration tests** with testcontainers using the real broker adapter.
4. **Build the `Orchestrator`** — connect, subscribe, stream, handle reconnection.
5. **Implement the in-process EventBus.**
6. **Build the Candle → Signal pipeline** with rule-based strategies first (no ML).

At the end of Phase 1, the platform can receive live market data and generate rule-based signals. This is the first integration milestone.

#### Phase 2: Persistence and API (Weeks 5-8)

1. **Implement PostgreSQL repositories** (`TradeRepository`, `SignalRepository`, `StrategyRepository`).
2. **Set up Alembic migrations.**
3. **Implement Redis pub/sub and cache.**
4. **Build the FastAPI REST interface** (`/v1/signals`, `/v1/trades`, `/v1/strategies`, `/v1/backtests`).
5. **Implement health checks and metrics.**
6. **Set up structlog logging with JSON output.**

At the end of Phase 2, the platform has a REST API, historical data querying, and operational monitoring.

#### Phase 3: Telegram (Weeks 7-9)

1. **Build the Telegram interface layer** — handlers, formatters, menus.
2. **Implement Telegram-specific use cases** (subscribe to signals, view portfolio, admin commands).
3. **Configure webhook or polling.**
4. **Set up authorization and rate limiting.**

At the end of Phase 3, the platform delivers signals and trade updates via Telegram. This is the first user-facing milestone.

#### Phase 4: Research and ML (Weeks 8-14)

1. **Build the DataCatalog** with DuckDB + Parquet for historical data.
2. **Implement the FeaturePipeline** with pandas-ta indicators.
3. **Build the backtesting engine** (vectorized phase first, event-driven phase second).
4. **Implement walk-forward validation.**
5. **Integrate MLflow** for experiment tracking.
6. **Train first ML model** on collected historical data.
7. **Implement the ML inference pipeline** in signal generation.

At the end of Phase 4, the platform supports ML-powered signals with validation and experimentation.

#### Phase 5: Production Hardening (Ongoing)

1. **Load testing** — verify signal latency, throughput, database performance.
2. **Chaos testing** — simulate broker disconnection, network failures, process crashes.
3. **Documentation** — API docs, operational runbooks, architecture updates.
4. **Monitoring dashboards** — Grafana dashboards for system health and strategy performance.
5. **Automated retraining pipeline** — scheduled model retraining with champion/challenger.

### 11.2 What I Would Avoid

| Don't Do | Instead |
|----------|---------|
| Don't build a custom WebSocket client for PocketOption | Use BinaryOptionsTools-v2's battle-tested implementation |
| Don't abstract every possible broker from day one | Abstract behind `BrokerPort` but only implement PocketOption. Add more adapters when needed. |
| Don't implement CQRS/event sourcing initially | Use simple repository pattern. Add event sourcing if audit requirements demand it. |
| Don't use a separate message queue (RabbitMQ/Kafka) | Start with in-process event bus + Redis pub/sub. Add Kafka when you have multiple services. |
| Don't implement distributed microservices | Stay as a monolith with clean internal boundaries. Extract services only when scaling demands it. |
| Don't optimize for performance before profiling | Use numpy/numba by default. Profile, then optimize the hot paths. |
| Don't implement a full web dashboard in the first release | Telegram + CLI + raw API is sufficient for a research platform. Web dashboard can follow. |
| Don't use `dependency_injector` or similar DI frameworks | Use FastAPI `Depends` for API, manual wiring for background tasks. |
| Don't commit to ML strategies before rule-based ones work | Rule-based strategies validate the pipeline. ML adds complexity that requires already-working infrastructure. |
| Don't hardcode strategy parameters in code | All strategy parameters in YAML files validated by Pydantic models. |

### 11.3 Trade-offs I Would Make

| Trade-off | Decision | Rationale |
|-----------|----------|-----------|
| Python speed vs development velocity | Choose velocity | Binary options signals don't require nanosecond latency. Python is fast enough. Rust where it matters (WebSocket I/O) is already handled by BinaryOptionsTools-v2. |
| Generic broker abstraction vs PocketOption depth | Prioritize PocketOption depth | A generic broker abstraction is useful but abstracting too early creates leaky abstractions. Build deep PocketOption support first, extract as needed. |
| Perfect testing vs shipping | Ship with 80% coverage | Domain: 95%+. Infrastructure: critical paths only. Interfaces: integration tests. Perfectionism delays feedback. |
| Event sourcing vs simple persistence | Start simple | Append-only event storage adds operational complexity. Use event sourcing only if audit/temporal query requirements justify it. PostgreSQL has all the features we need. |
| Real-time vs batch research | Support both | Real-time pipeline for live trading. Batch research backtest for strategy development. Same code, different execution modes. |
| Managed infrastructure vs self-hosted | Docker Compose for dev, self-managed for prod | Until scaling demands managed services, Docker Compose with PostgreSQL and Redis containers is sufficient and keeps costs predictable. |

### 11.4 Decisions That Should Never Change

These architectural decisions are foundational. Changing them would require a rewrite:

1. **Clean Architecture layering.** The dependency rule (domain ← application ← infrastructure ← interfaces) is non-negotiable. It is the only thing that prevents the system from becoming an unmaintainable monolith.

2. **Domain isolation.** The domain layer must never import from infrastructure, must never depend on a specific broker, and must never contain HTTP, WebSocket, or database code.

3. **BinaryOptionsTools-v2 as infrastructure.** The broker library is always an implementation detail behind `BrokerPort`. No domain entity, no application use case, no interface handler should ever import `binaryoptionstools`.

4. **Event-driven signal pipeline.** The pipeline (Candle → Features → Signal → Risk → Trade → Log) communicates via events. This enables testing, monitoring, and extension at every stage.

5. **Pydantic for everything.** Every external boundary, every configuration, every serializable model uses Pydantic v2. This is not negotiable — it provides validation, serialization, documentation, and type safety in one package.

6. **Decimal for money.** All monetary computations use `Decimal`. Floating-point for money is a bug that will eventually cost real money.

7. **Async-first concurrency.** The platform uses async Python throughout. Synchronous blocking in async context is a bug. Every database call, network request, and computation must be async-friendly.

8. **Experiment reproducibility.** Every signal, trade, and backtest must be traceable to the exact code version, data version, and configuration that produced it. This is the foundation of scientific trading.

9. **No business logic in interface handlers.** Telegram, REST, CLI, future interfaces — they parse input and format output. Nothing more.

10. **Monorepo with explicit internal boundaries.** Single repository with clear package boundaries. Split into separate repos only when the team grows beyond ~5 engineers or deployment independence requires it.

---

*This document is a living architectural foundation. It should be reviewed, challenged, and updated as the platform evolves. Every significant deviation from the principles outlined here should be recorded as an Architecture Decision Record (ADR) in `docs/adr/`.*

*End of Architecture Report*
