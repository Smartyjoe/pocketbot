# Trading Platform Architecture Analysis

> Research compiled June 2026 for the Binary Options Research Platform project.
> Goal: Extract architectural patterns worth adopting (and pitfalls worth avoiding) from 6 major open-source trading frameworks.

---

## Table of Contents

1. [Freqtrade](#1-freqtrade)
2. [QuantConnect LEAN](#2-quantconnect-lean)
3. [Backtrader](#3-backtrader)
4. [VectorBT](#4-vectorbt)
5. [Hummingbot](#5-hummingbot)
6. [NautilusTrader](#6-nautilustrader)
7. [Cross-Platform Comparison](#7-cross-platform-comparison)
8. [Recommendations for Our Platform](#8-recommendations-for-our-platform)

---

## 1. Freqtrade

**Language:** Python | **Stars:** 52k | **License:** GPL-3.0
**Domain:** Crypto spot/futures trading bot

### Project Structure

```
freqtrade/
├── freqtrade/
│   ├── commands/         # CLI entry points (backtesting, hyperopt, trade, etc.)
│   ├── configuration/    # Config loading, validation, schema
│   ├── data/             # Data download, conversion, OHLCV management
│   ├── enums/            # Enums (SignalDirection, TradeState, etc.)
│   ├── exchange/         # Exchange abstraction (ccxt wrapper)
│   ├── freqai/           # ML-based prediction subsystem
│   ├── optimize/         # Backtesting & hyperopt engines
│   ├── persistence/      # SQLite models (Trade, PairLock, etc.)
│   ├── plugins/          # Pairlists, protections, data providers
│   ├── resolvers/        # Dynamic strategy/plugin loading
│   ├── rpc/              # Telegram, WebUI, REST API interfaces
│   ├── strategy/         # IStrategy interface, strategy wrappers
│   ├── freqtradebot.py   # Main trading loop orchestration
│   ├── wallets.py        # Balance tracking
│   └── worker.py         # App lifecycle (trading/webserver mode)
├── tests/
└── user_data/            # User strategies, configs, data, logs
```

### Strategy Abstraction (IStrategy)

The core interface is `freqtrade/strategy/interface.py` (1900+ lines). Strategies inherit from `IStrategy` and override:

```python
class IStrategy(ABC):
    # — Lifecycle —
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame: ...
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame: ...
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame: ...

    # — Per-candle callbacks —
    def confirm_trade_entry(self, pair, order_type, amount, ...) -> bool: ...
    def confirm_trade_exit(self, pair, ...) -> bool: ...
    def custom_stake_amount(self, pair, current_time, ...) -> float: ...
    def custom_exit(self, pair, ...) -> Optional[str]: ...
    def check_buy_timeout(self, ...) -> bool: ...
    def check_sell_timeout(self, ...) -> bool: ...

    # — Optional lifecycle hooks —
    def bot_loop_start(self, **kwargs) -> None: ...
    def bot_loop_end(self, **kwargs) -> None: ...

    # — Informative (notebook-accessible) —
    def leverage(self, pair, current_time, current_rate, ...) -> float: ...
    def min_entry_pos_adjust(self, ...) -> float: ...
```

**Key design choice:** The strategy works on **whole DataFrames** (vectorized in `populate_*`), then the engine iterates row-by-row during backtesting/live. This is a hybrid approach — pandas for indicator computation, event-loop for trade management.

### Plugin System

Freqtrade has 4 plugin axes:
1. **Pairlists** (`plugins/pairlist/*`) — Static, VolumePairList, AgeFilter, SpreadFilter, etc. Dynamic pair selection.
2. **Protections** (`plugins/protections/*`) — CooldownPeriod, LowProfitPairs, MaxDrawdown, StoplossGuard. Cooldown logic between trades.
3. **Data Providers** — Abstract data source interface (exchange, external APIs).
4. **Exchanges** (`exchange/*`) — Thin wrapper over `ccxt` with exchange-specific overrides.

All plugins are resolved dynamically via `resolvers/` using Python's `importlib`.

### Data Pipeline

```
Exchange (ccxt)
    ↓ fetch_ohlcv()
Historical Data (JSON/Parquet)
    ↓ populate_indicators()    ← Strategy adds SMA, RSI, etc.
    ↓ populate_entry_trend()   ← Strategy defines entry signals
    ↓ populate_exit_trend()    ← Strategy defines exit signals
    ↓
Backtesting Engine or Live Trade Loop
    ↓ iterate rows → check signals → manage positions → record trades
    ↓
SQLite persistence (Trades, Orders, Pairlocks)
```

**Critical detail:** Indicators are pre-computed on the entire DataFrame (vectorized), but signal evaluation is row-by-row. This means lookahead bias is possible if `populate_*` uses future data accidentally. Freqtrade provides `lookahead-analysis` and `recursive-analysis` commands to detect this.

### Backtesting Architecture

`optimize/backtesting.py` uses a `Backtesting` class that:
1. Loads historical data for all pairs
2. Calls `populate_*` on each pair's DataFrame
3. Iterates time-synchronized across all pairs
4. Maintains an in-memory copy of the exchange interface (mock orders, mock balance)
5. Produces a `BacktestResult` with trade history, profit/loss, stats

**Dry-run mode** shares the same code path as live but uses virtual funds.

### Hyperparameter Optimization

`optimize/hyperopt.py` integrates with `scikit-optimize` and `Optuna`:
- Defines a search space over strategy parameters
- Runs full backtests for each parameter set
- Minimizes a configurable loss function (Sharpe, Sortino, Calmar, custom)
- Supports multi-GPU via joblib parallelism
- Stores results in SQLite for later analysis

### Configuration System

- JSON config files with JSON Schema validation
- Config merges: default → user config → CLI args → environment variables
- `config_schema/` defines the full JSON Schema
- Runtime config resolution via `configuration/` module

### Exchange Handling

- Uses `ccxt` as universal exchange abstraction layer
- Exchange-specific overrides for non-standard behaviors (Binance futures margin mode, Kraken order minimums)
- Exchange class wraps ccxt with retry logic, rate limiting, and dry-run mock

### Testing Approach

- Comprehensive pytest suite in `tests/`
- Test fixtures for exchange mocks, dataframes, configs
- Property-based testing with hypothesis
- CI runs on every PR with multiple Python versions
- Code coverage tracked via CodeCov

### What to Adopt

- **DataFrame-based indicator computation** — clean separation between signal generation (vectorized) and trade execution (event-driven)
- **Resolver pattern** for dynamic strategy/plugin loading without imports
- **Config schema validation** with JSON Schema
- **CLI command structure** — clean separation of concerns via subcommands
- **Lookahead-bias detection tooling**
- **Dry-run shares backtest code** — no divergence between simulation and live
- **Plugin architecture** (pairlists, protections) is cleanly separated

### What to Avoid

- **Monolithic IStrategy interface** (1900 lines) — too many optional methods. Use smaller, composable traits/mixins
- **Pandas DataFrame passing** between strategy methods — easy to accidentally mutate shared state
- **SQLite for trade persistence** works but becomes a bottleneck at high frequency
- **Exchange abstraction is too thin** — mostly just passes through ccxt, limited exchange-specific modeling
- **Backtesting speed** — row-by-row iteration is slow for large datasets

---

## 2. QuantConnect LEAN

**Language:** C# (core) + Python (algorithms) | **Stars:** 20.3k | **License:** Apache-2.0
**Domain:** Multi-asset (equities, options, futures, forex, crypto)

### Overall Architecture

LEAN is an **event-driven, service-oriented** architecture. Key assemblies:

```
Lean/
├── Algorithm/           # QCAlgorithm base class (strategy API)
├── Algorithm.CSharp/    # Example strategies in C#
├── Algorithm.Python/    # Python strategy wrapper (bridges C# → Python)
├── Algorithm.Framework/# Composable modules (universe, alpha, portfolio, execution, risk)
├── Engine/              # Core orchestration
│   ├── AlgorithmManager.cs    # Main loop: time slice → data → algorithm → orders
│   ├── DataFeeds/             # Subscription-based data pipeline
│   ├── TransactionHandlers/   # Order processing
│   ├── RealTime/              # Timer/schedule events
│   ├── Results/               # Result handling (API, storage)
│   ├── Setup/                 # Algorithm initialization
│   └── Server/                # Job management
├── Common/              # Shared domain models, data types
├── Indicators/          # 100+ technical indicators
├── Brokerages/          # Broker adapters (IB, Bitfinex, GDAX, etc.)
├── Api/                 # QuantConnect cloud API client
├── Configuration/       # Config loading
├── Data/                # Sample/test data
├── Optimizer/           # Parameter optimization
├── Research/            # Jupyter integration
└── Tests/               # Test suite
```

### Engine Architecture

The `Engine.cs` orchestrates the system lifecycle:
1. **Setup phase**: Load algorithm, attach data feeds, initialize broker
2. **Run phase**: `AlgorithmManager` loops over time slices:
   - Get next data from `DataFeed`
   - Push data to `Algorithm`
   - Collect `Insight`s from Algorithm Framework
   - Route through Portfolio Construction → Risk → Execution models
   - Process fills from `TransactionHandler`
   - Update portfolio state
   - Fire scheduled events
3. **Results phase**: Package results and send via `ResultHandler`

### Algorithm Framework (QCAlgorithm)

QCAlgorithm is the user-facing base class. The **Algorithm Framework** splits strategy into 5 pluggable modules:

| Module | Responsibility |
|--------|----------------|
| **Universe Selection** | Which assets to trade |
| **Alpha Creation** | Generate signals/insights |
| **Portfolio Construction** | Weight assets based on insights |
| **Execution Model** | How to fill orders |
| **Risk Management** | Position sizing, hedging, stops |

```csharp
class MyAlgorithm : QCAlgorithm {
    public override void Initialize() {
        SetUniverseSelection(new FundamentalUniverseModel());
        AddAlpha(new RsiAlphaModel());
        SetPortfolioConstruction(new EqualWeightingPortfolioConstructionModel());
        SetExecution(new ImmediateExecutionModel());
        SetRiskManagement(new MaximumDrawdownPercentModel(0.05m));
    }
}
```

### Data Pipeline

```
Data Sources (files, API, streaming)
    ↓
Subscription Manager (manages multiple data subscriptions)
    ↓
Data Feeds (ZipFile, Live, Remote)
    ↓ Consolidators (aggregate ticks → bars, bars → larger bars)
    ↓
Algorithm.OnData(Slice)  ← event-driven per time step
    ↓
Indicators update automatically (auto-wired to data)
    ↓
Algorithm Framework modules
    ↓
Orders → TransactionHandler → Broker → Exchange
```

**Key concepts:**
- **Subscription** = one data stream (e.g., "SPY minute trade bars")
- **Consolidator** = aggregates raw data into desired format (tick → second, minute → hour)
- **Slice** = all data for a single timestamp (all subscribed assets)
- **Symbol** = a security identifier (underlying + market + type)

### Event System

LEAN uses a **polling event model** within the time loop, not a pub/sub system:

```csharp
// Called every time step with all new data
public void OnData(Slice slice) { ... }

// Called when orders change state
public void OnOrderEvent(OrderEvent orderEvent) { ... }

// Called at scheduled intervals
public void OnScheduled(DateRules, TimeRules, Action) { ... }

// Insight events (from Alpha model)
Insight.OnExpired(Action<Insight>)
```

### Plugin Architecture

Everything is an interface:
- `IDataFeed` — data source abstraction
- `IBrokerage` — broker connection (IB, GDAX, etc.)
- `ITransactionHandler` — order validation/processing
- `IResultHandler` — how results are stored/displayed
- `IAlphaModel`, `IPortfolioConstructionModel`, `IExecutionModel`, `IRiskManagementModel`

### Research vs Live Trading

- **Research**: Jupyter Lab environment with `QuantBook` — a research-optimized version of QCAlgorithm
- **Backtesting**: Same algorithm code, engine runs historical data through identical pipeline
- **Live**: Same algorithm code, engine switches to live data feed + real brokerage
- **Key principle**: one code path for all modes

### What to Adopt

- **Algorithm Framework modules** — clean separation of concerns (universe → alpha → portfolio → execution → risk)
- **Consolidator pattern** — clean data aggregation abstraction
- **Subscription-based data management** — declarative, typed data streams
- **Same code for backtest and live** — the gold standard
- **Service-oriented engine design** — each concern is a replaceable interface
- **Multi-asset symbol model** — thorough type system for securities
- **Insight-based alpha model** — signals are first-class objects with direction, confidence, magnitude, duration

### What to Avoid

- **C# core** — heavy dependency, complex build pipeline vs Python-native. However, the architecture transcends language.
- **Polling event model** — `OnData` receives everything; can be overwhelming. Fine-grained subscriptions are better.
- **Assembly complexity** — 20+ projects in the solution. Our platform should be simpler.
- **Engine loop coupling** — `AlgorithmManager` does too much (data, alpha, portfolio, risk, execution in one loop).
- **Performance for high-frequency** — event-driven loop can be a bottleneck.

---

## 3. Backtrader

**Language:** Python | **Stars:** 22.2k | **License:** GPL-3.0
**Domain:** General-purpose backtesting

### Cerebro Engine Architecture

`Cerebro` is the central orchestrator:

```python
cerebro = bt.Cerebro()
cerebro.addstrategy(MyStrategy, period=20)
cerebro.adddata(data)
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addsizer(bt.sizers.FixedSize, stake=100)
cerebro.broker.setcash(10000.0)
results = cerebro.run()  # returns list of strategy instances
cerebro.plot()
```

`Cerebro.run()` does:
1. Preload all data feeds
2. Instantiate strategies
3. Loop time-synchronized across all data feeds
4. For each tick/bar: feed data → run `next()` on strategies → execute orders → notify analyzers/observers.
5. Supports parallel execution for parameter optimization (`optreturn` mode).

### Strategy / Lines / Indicators System

Everything is a **Lines object** — a time series with named lines (`.close`, `.high`, `.low`, etc.).

```python
class SmaCross(bt.Strategy):
    params = dict(period=10)

    def __init__(self):
        self.sma = bt.ind.SMA(self.data, period=self.params.period)
        # Lines objects can be compared directly — creates signal lines
        self.crossover = bt.ind.CrossOver(self.data, self.sma)

    def next(self):
        if self.crossover > 0:      # bullish crossover
            self.buy()
        elif self.crossover < 0:    # bearish crossover
            self.sell()
```

**Key concept:** Operators on `Lines` objects create new `Lines` objects during `__init__`, which auto-compute during `next()`. This enables declarative indicator composition.

### Data Feeds Framework

Data feeds are first-class objects:
- `bt.feeds.YahooFinanceData`, `bt.feeds.PandasData`, `bt.feeds.GenericCSVData`
- Support **Replay** (convert tick → bar at bar close) and **Resample** (convert 1min → 5min)
- **Filters** can modify data in-flight (e.g., Renko brick simulation)
- Multiple timeframes per strategy (daily + weekly data)

### Broker Simulation

`bt.brokers.BrokerBase` provides:
- Order types: Market, Limit, Stop, StopLimit, StopTrail, StopTrailLimit, OCO, Brackets
- Commission schemes (percentage, fixed, tiered)
- Slippage models (fixed, percentage, custom)
- Volume-based filling (partial fills)
- Short-selling support
- Cheat-on-Open / Cheat-on-Close modes (orders filled at next bar's OHLC)

### Observer / Analyzer System

- **Analyzers**: Post-run analysis (Sharpe, DrawDown, TimeReturn, VWR, SQN, TradeAnalyzer). Attached via `cerebro.addanalyzer()`.
- **Observers**: Real-time statistics during run (PortfolioValue, BuySell, DrawDown, Trades, Benchmark). Written to the plot automatically.
- Both are `Lines` objects — they participate in the same data flow.

### Strengths

- **Beautifully designed Lines abstraction** — composable, declarative, mathematically elegant
- **Extensive order types** — covers real-world scenarios
- **Commission + Slippage + Volume filling** — realistic broker simulation
- **Signal-based strategies** — can bypass Strategy class entirely for simple strategies
- **PyFolio + QuantStats integration**
- **Plotting** built-in

### Limitations

- **Single-threaded** — parameter optimization is process-based (multiprocessing)
- **No native live trading** — requires external stores/brokers
- **Performance** — Python loop per bar/strategy; max ~50k bars/sec
- **No built-in hyperparameter optimization**
- **Not designed for high-frequency** (tick-level backtesting is slow)
- **Maintenance** — project has been in low-maintenance mode since ~2020
- **No native multi-asset portfolio rebalancing** — positions are managed per-asset

### What to Adopt

- **Lines abstraction** — composable time series with operator overloading is elegant. Worth emulating.
- **Cerebro's composable architecture** — addstrategy + adddata + addanalyzer + addsizer + broker configuration
- **Live trading and backtesting share strategy code** (though live is limited in practice)
- **Filter chain pattern** — data flows through transformation pipeline
- **Signal-based strategy** as alternative to explicit state-machine strategies
- **Broker simulation depth** — commission + slippage + volume filling + partial fills

### What to Avoid

- **Metaclass-heavy implementation** — hard to debug, hard to extend
- **No async support** — everything is synchronous
- **Tight coupling** between Lines and everything else
- **Poor performance at scale** — not suitable for thousands of assets
- **Dead project risk** — no active maintenance since 2020

---

## 4. VectorBT

**Language:** Python (+ Rust engine option) | **Stars:** 8.1k | **License:** Apache 2.0 + Commons Clause
**Domain:** High-performance backtesting, strategy research

### Vectorized vs Event-Driven Architecture

VectorBT is **vectorized-first**: operations apply to entire arrays at once using NumPy, Numba, and (optionally) Rust.

```python
# Event-driven (Freqtrade/Backtrader):
for bar in bars:
    if crossover(sma_fast[bar], sma_slow[bar]):
        portfolio.trade(...)

# Vectorized (VectorBT):
entries = fast_ma.ma_crossed_above(slow_ma)   # boolean array
exits  = fast_ma.ma_crossed_below(slow_ma)    # boolean array
pf = vbt.Portfolio.from_signals(price, entries, exits)  # all at once
```

**Performance:** 10,000 parameter combinations across 3 assets in seconds.

### NumPy/Pandas/Numba Engine

- Core types are `pd.DataFrame` and `np.ndarray`
- **Numba JIT** compiles hot loops (signals → portfolio simulation)
- **Optional Rust engine** (`vbt[rush]`) replaces Numba with precompiled Rust for: signal generation, portfolio simulation, indicator computation
- **Broadcasting** — operations automatically vectorize across parameters and assets:

```python
# Run SMA for all window sizes 2-100 simultaneously
windows = np.arange(2, 101)
fast_ma, slow_ma = vbt.MA.run_combs(price, window=windows, r=2)
```

### Portfolio Simulation

`vbt.Portfolio` class provides multiple construction modes:
- `from_holding(price, init_cash)` — buy and hold
- `from_signals(price, entries, exits, ...)` — entry/exit signal arrays
- `from_random_signals(price, ...)` — monte carlo simulation
- `from_orders(price, size, price, ...)` — manual order lists
- `from_trades(price, open, close, ...)` — from pre-computed trades

Each returns a `Portfolio` with full analytics (returns, drawdowns, trades, sharpe, etc.).

### Indicator Factory

Indicators are generated via `vbt.IndicatorFactory`:

```python
MyIndicator = vbt.IndicatorFactory(
    class_name="MyIndicator",
    short_name="myind",
    input_names=["price"],
    param_names=["period"],
    output_names=["value"],
).with_apply_func(
    lambda price, period: price.rolling(period).mean(),
    takes_1d=True,  # operates on 1D arrays
)
```

This pattern in v2 is evolving toward a more pandas-native API with custom accessors.

### Signals Generation

Signals are boolean arrays or numeric arrays (for ranking):
- **Binary signals**: entry/exit as boolean arrays
- **Ranking signals**: `vbt.signals.ranking` for top-N selection
- **Distribution**: map signals to portfolio actions
- **Label generation**: for ML workflows (triple-barrier, etc.)

### What to Adopt

- **Vectorized-first approach** for research/backtesting — orders of magnitude faster for parameter sweeps
- **Numba/Rust acceleration** for hot paths
- **`Portfolio.from_signals`** pattern — clean separation of signal generation from execution simulation
- **Flexible broadcasting** — automatic parameter combination
- **IndicatorFactory** — declarative indicator definition
- **Robustness testing** — built-in walk-forward analysis
- **Label generation** for ML

### What to Avoid

- **Commons Clause license** — restricts commercial use. Our platform needs permissive licensing.
- **No live trading** — research-only tool
- **No event-driven mode** — can't simulate order latency, partial fills, or multi-asset synchronization
- **Memory intensive** — entire dataset in RAM (not suitable for infinite streaming data)
- **Limited broker modeling** — no commission curves, slippage models as sophisticated as Backtrader
- **Not suitable for real-time** — architecture fundamentally batch-oriented

---

## 5. Hummingbot

**Language:** Python (+ Cython for performance) | **Stars:** 19k | **License:** Apache 2.0
**Domain:** High-frequency crypto market making, arbitrage

### Strategy Abstraction

Hummingbot uses a **script-based strategy system** with a controller pattern:

```python
# Example: Pure Market Making strategy
class PureMarketMakingStrategy(MarketMakingStrategy):
    async def on_tick(self):
        # Place bids and asks around mid-price
        order_levels = self.create_order_levels(
            self.mid_price,
            self.config.order_amount,
            self.config.spread
        )
        for level in order_levels:
            await self.place_order(level)
```

Strategies are `Script` classes (or `V2Script`) with event handlers:
- `on_tick()` — periodic tick handler
- `on_trade()` — when a trade occurs
- `on_order_filled()` — when an order fills
- `on_status()` — status report
- `on_start()` / `on_stop()`

The newer **V2 architecture** uses `Controller` and `Executor` abstractions:
- **Controller**: Pure data logic (signal computation, risk rules)
- **Executor**: Action execution (place orders, manage positions)

### Connector Architecture

**Connectors** are the key abstraction — they standardize exchange APIs:

```
hummingbot/
├── connector/
│   ├── exchange/
│   │   ├── binance/        # REST + WebSocket adapter
│   │   ├── coinbase/       # REST + WebSocket adapter
│   │   ├── kraken/
│   │   └── ...
│   ├──衍生品/
│   │   ├── binance_perpetual/
│   │   └── ...
│   └── gateway/            # DEX connectors via Gateway middleware
│       ├── uniswap/
│       ├── pancakeswap/
│       └── ...
```

Each connector provides:
- `ExchangeBase`: Standard interface (get_order_book, place_order, cancel_order, get_balance, ...)
- `WebSocketFeed`: Real-time data streaming
- `DataSource`: Historical data
- `Constants`: Exchange-specific config (rate limits, order types, fees)

### Data Flow Pipeline

```
Exchange WebSocket (real-time)
    ↓
Connector (normalizes to internal types)
    ↓
OrderBook (in-memory, maintained via delta updates)
    ↓
Strategy.on_tick() / on_trade()
    ↓
Decision → Create Order → Connector.place_order()
    ↓
Order tracking → fills → position updates
    ↓
Persistence (SQLite + Prometheus metrics)
```

### Event System

Async event-driven using Python asyncio:
- Event loop ticks at configurable interval
- Strategy subscribes to market data events
- Order state machine (CREATED → OPEN → PARTIALLY_FILLED → FILLED / CANCELED / FAILED)
- Custom event bus for inter-module communication

### What to Adopt

- **Connector abstraction** — clean interface for exchange integration. Worth modeling our platform's broker/exchange layer after this.
- **Controller/Executor pattern** (V2) — separates signal logic from execution. Cleanly maps to our binary options signal generation vs trade placement.
- **Gateway pattern for DEX** — middleware to normalize decentralized exchange APIs
- **Async event-driven architecture** — appropriate for real-time trading
- **Order state machine** — formal state model for trade lifecycle
- **Script-based strategies** — hot-reloadable user code

### What to Avoid

- **Cython dependency** — adds build complexity. Pure Python or Rust-native is simpler.
- **Monolithic connector interface** — each connector implements dozens of methods
- **MySQL/SQLite persistence** — not fast enough for HFT
- **Complex deployment** — Docker + Gateway + multiple processes
- **Poor documentation** on internal architecture
- **Limited backtesting** — historically weak; improving with V2

---

## 6. NautilusTrader

**Language:** Rust (core) + Python (control plane) | **Stars:** 24.3k | **License:** LGPL-3.0
**Domain:** Multi-asset, multi-venue, production-grade trading

### Core Architecture

```
nautilus_trader/
├── core/           # Rust core (via PyO3) — clock, UUID gen, messages
├── model/          # Domain models (Order, Position, Instrument, Price, Quantity)
├── trading/        # Strategy, Portfolio, OrderManagementSystem
├── execution/      # Execution engine, order matching
├── backtest/       # Backtesting engine
├── live/           # Live execution components
├── data/           # Data catalog, data engines
├── indicators/     # Technical indicators
├── accounting/     # Account management, P&L calculation
├── risk/           # Risk management
├── analysis/       # Trade analysis, metrics
├── cache/          # In-memory state cache
├── persistence/    # Database persistence (Redis, SQL)
├── serialization/  # Message serialization
├── adapters/       # Exchange integrations (binance, bybit, ib, etc.)
├── config/         # Configuration management
├── system/         # System topology
└── test_kit/       # Testing utilities
```

**Core philosophy:** Rust provides the **deterministic event-driven runtime**. Python is the **control plane** for strategy logic and system composition.

### Actor/Strategy Model

```python
class MyStrategy(Strategy):
    def on_start(self):
        # Subscribe to data
        self.subscribe_bars(BarType.from_str("ETHUSDT.PERP.BINANCE-1.MINUTE-LAST"))
        self.subscribe_quote_ticks(InstrumentId.from_str("ETHUSDT.PERP.BINANCE"))

    def on_bar(self, bar: Bar):
        # Compute indicators
        self.sma.update(bar.close)
        if self.sma.value > bar.close:
            self.buy()

    def on_fill(self, order: Order, fill: Fill):
        print(f"Filled: {fill}")
```

**Key difference from other platforms:** Strategies are **actors** — they have isolated state, message-based communication, and a lifecycle managed by the engine.

### Data Catalog

NautilusTrader introduces a **Data Catalog** concept:
- Parquet-based storage for historical data
- Catalog provides `load()` and `store()` methods
- Supports tick data, bars, order book snapshots
- Integration with Databento, Tardis, and other data providers
- Time-based partitioning for efficient querying

### Backtesting Engine

The backtesting engine provides **nanosecond-precision simulation**:
- Multiple venues, instruments, strategies simultaneously
- Simulated exchange matching engines
- Support for quote tick, trade tick, bar, and order book data
- Identical code path to live execution

```python
# Backtest configuration
engine = BacktestEngine(config)
engine.add_venue(venue, latency_model=LatencyModel())
engine.add_data(parquet_data)
engine.add_strategy(strategy)
engine.run()
```

### Live Execution

The same `Strategy` class runs live with zero code changes:
- `LiveExecutionEngine` replaces `BacktestEngine`
- Adapters connect to real exchanges
- Execution messages flow through the same message bus
- Redis-backed state persistence for crash recovery

### What to Adopt

- **Rust-native core with Python control plane** — best of both worlds (performance + productivity). Worth considering for our platform.
- **Deterministic event-driven architecture** — same semantics in backtest and live
- **Data Catalog** — clean abstraction for historical data management
- **Actor-based strategy model** — isolated state, message-passing
- **Nanosecond precision** — important for high-frequency timing
- **Caching + persistence separation** — Redis for speed, SQL for durability
- **Explicit latency modeling** in backtesting
- **Modular adapter architecture** — clean integration pattern

### What to Avoid

- **Complex build system** — Rust + Python + Cython + PyO3. Steep learning curve.
- **LGPL license** — may be restrictive for commercial use
- **Young ecosystem** — rapidly evolving, breaking API changes
- **Windows high-precision limitation** — 128-bit mode not available on Windows
- **Documentation still maturing** — some concepts lack thorough docs
- **Over-engineered for simple use cases** — the actor model adds complexity

---

## 7. Cross-Platform Comparison

| Feature | Freqtrade | LEAN | Backtrader | VectorBT | Hummingbot | NautilusTrader |
|---------|-----------|------|------------|----------|------------|----------------|
| **Primary Language** | Python | C# + Python | Python | Python (+ Rust) | Python (+ Cython) | Rust + Python |
| **Execution Model** | Hybrid (DF+Event) | Event-driven | Event-driven | Vectorized | Async Event | Deterministic Event |
| **Strategy Abstraction** | IStrategy class | QCAlgorithm + Framework | Strategy class | Signals as arrays | Script + Controller | Actor-based |
| **Backtest ↔ Live Parity** | Yes (dry-run) | Yes | Partial | No live | Limited | Full parity |
| **Plugin System** | Pairlist, Protection, Exchange | Full interface-based | Analyzer, Observer, Sizer, Broker | N/A (library) | Connector, Executor | Adapter-based |
| **Data Pipeline** | OHLCV CSV/Parquet | Subscription + Consolidator | Lines + Feeds | DataFrame | WebSocket → Connector | Data Catalog |
| **Hyperparameter Opt** | scikit-optimize, Optuna | QuantConnect cloud | via `optreturn` | Native (vectorized) | No | Planned |
| **Real-time Capable** | Yes | Yes | Limited (IB, Oanda) | No | Yes | Yes |
| **Multi-Asset** | Crypto only | Full (9 asset classes) | Any (via feeds) | Any (pandas) | Crypto (CEX + DEX) | Full |
| **Performance** | Medium | Medium | Low | Very High | High | Very High |
| **License** | GPL-3.0 | Apache-2.0 | GPL-3.0 | Commons Clause | Apache-2.0 | LGPL-3.0 |
| **Active Development** | Very active (2026) | Very active | Dormant | Active | Very active | Very active |

### Key Architectural Differences

**Vectorized vs Event-Driven:**
- VectorBT does everything on arrays — fast for research, can't simulate realistic execution
- LEAN/Backtrader/Hummingbot/Nautilus do bar-by-bar — slower but realistic
- Freqtrade splits the difference: vectorized indicators, event-driven execution

**Strategy Abstraction Complexity:**
- Simpler (VectorBT): `entries = condition; pf = Portfolio.from_signals(entries)` — 2 lines
- Most complex (LEAN): 5-module framework with university selection, alpha, portfolio construction, execution, risk — powerful but heavy

**Plugin/Extensibility:**
- LEAN has the cleanest plugin architecture (all interfaces)
- Freqtrade has practical plugins (pairlists, protections)
- NautilusTrader has the most modular adapter system

---

## 8. Recommendations for Our Binary Options Research Platform

### Adopt These Patterns

#### 1. **Hybrid Computation Model** (Freqtrade + VectorBT)
Our platform should use **vectorized indicator computation** (pandas/numpy) for signal generation, but **event-driven simulation** for binary option lifecycle (expiry, payout, settlement). This gives us research speed + realistic simulation.

```
Data → Vectorized indicators → Signal generation (arrays)
    ↓
Event-driven loop: evaluate signals → place binary options → handle expiry
    ↓
Portfolio tracking → P&L → metrics
```

#### 2. **Controller/Executor Pattern** (Hummingbot V2)
- **Controller**: Pure signal logic. Takes OHLCV data, returns entry/exit signals (buy CALL/PUT at specific strike/expiry).
- **Executor**: Handles the binary option lifecycle — order placement, expiry monitoring, payout collection, position tracking.
- **Separation allows**: swap backtesting executor ↔ live executor without changing strategy logic.

#### 3. **Data Catalog** (NautilusTrader)
A clean abstraction for storing, loading, and querying historical binary options data:
- Parquet-based storage for efficiency
- Catalog methods: `load_btc_options(datetime_range)`, `store_ohlcv(data)`
- Support for both raw data and pre-computed features

#### 4. **Config Validation with Pydantic** (Freqtrade inspiration)
- Full Pydantic models for all configuration
- JSON Schema generation for UI
- Environment variable override support
- Config profiles (research, paper, live)

#### 5. **Composable Signal Pipeline** (Backtrader Lines inspiration)
A pipeline pattern where signals flow through transformation stages:

```python
pipeline = (
    DataSource("binance", "BTC/USDT")
    | Indicator("RSI", period=14)
    | Indicator("BBANDS", period=20)
    | Signal("rsi < 30 AND price < lower_band", direction="CALL")
    | ExpiryFilter(min_expiry=5, max_expiry=60)  # minutes
    | RiskCheck(max_daily_loss=0.05)
    | Executor(paper=True)
)
```

#### 6. **Event-Driven Core Loop** (LEAN / NautilusTrader)
```python
class Engine:
    def run(self):
        while self.has_more_data():
            # 1. Advance time
            # 2. Deliver new data to all strategies
            # 3. Process strategy signals → determine binary option entries
            # 4. Check for expired options → settle P&L
            # 5. Update portfolio
            # 6. Notify analytics/observers
```

#### 7. **Nanosecond Timestamps** (NautilusTrader)
Binary options expire at precise times. Use nanosecond timestamps internally for:
- Accurate backtesting of expiry timing
- Latency measurement in live trading
- Synchronization across multiple data sources

#### 8. **Explicit Broker/Exchange Model** (LEAN + Hummingbot)
```python
class BinaryOptionsBroker(ABC):
    @abstractmethod
    async def place_option(self, option: BinaryOption) -> OptionReceipt: ...
    @abstractmethod
    async def check_expiry(self, option_id: str) -> OptionResult: ...
    @abstractmethod
    async def get_payout(self, option_id: str) -> float: ...

class BacktestBroker(BinaryOptionsBroker): ...  # deterministic simulation
class PaperBroker(BinaryOptionsBroker): ...      # real data, virtual money
class LiveBroker(BinaryOptionsBroker): ...       # real money
```

#### 9. **Signal-Based Strategies** (VectorBT + Freqtrade)
```python
class MySignalStrategy:
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame with 'entry', 'direction', 'expiry', 'strike' columns."""
        df['rsi'] = compute_rsi(df['close'], 14)
        df['entry'] = df['rsi'] < 30
        df['direction'] = 'CALL'
        df['expiry'] = df.index + pd.Timedelta(minutes=15)
        return df
```

This is simpler than a full class-based strategy API and works well with vectorized backtesting.

#### 10. **Lookahead Bias Detection** (Freqtrade)
Built-in tools to detect when strategy accidentally uses future data:
- Compare signal timestamps vs data timestamps
- "Peek" detection: flag if indicators use data from > T
- Walk-forward validation

### Avoid These Patterns

#### 1. **Monolithic Base Classes** (Freqtrade IStrategy at 1900 lines)
Instead: small, composable traits/mixins/interfaces.

#### 2. **Purely Vectorized Execution** (VectorBT)
Binary options need realistic expiry simulation. Full vectorization can't model:
- Early exercise decisions
- Partial fills
- Order latency
- Multiple concurrent options with different expiries

Use vectorized for research, event-driven for production backtesting.

#### 3. **Dormant/Unmaintained Dependencies** (Backtrader)
Don't build on Backtrader. Its ecosystem is dead. Use its design patterns but implement fresh.

#### 4. **Single-Language Traps**
- Python-only: accept that hot paths need acceleration (Numba, Rust, or Cython)
- Rust-only: accept that strategy development needs Python flexibility
- Solution: Python control surface + compiled core (NautilusTrader model)

#### 5. **License Restrictions**
- Avoid GPL/LGPL for core platform code (our users may want commercial use)
- Apache 2.0 or MIT recommended
- CC exceptions: Commons Clause prohibits selling the software itself

#### 6. **Over-Engineering** (LEAN)
LEAN's 5-module Framework (universe → alpha → portfolio → execution → risk) is powerful but heavy.
For binary options, start simpler:
- **Signal generation** (equivalent to Alpha)
- **Risk management** (max loss per day/hour)
- **Execution** (option placement + expiry handling)

Add complexity only when needed.

### Recommended Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Core Engine** | Rust (via PyO3) | Performance + Python bindings. Model after NautilusTrader. |
| **Strategy Layer** | Python | Flexibility for researchers. Typed Pydantic models. |
| **Backtesting** | Hybrid (vectorized + event-driven) | Fast research + realistic simulation |
| **Data Storage** | Parquet + Data Catalog | Efficient, queryable, standard |
| **Live Trading** | Async Python + Rust core | Real-time capable |
| **Config** | Pydantic + JSON Schema | Validation, documentation, UI generation |
| **State** | Redis (cache) + PostgreSQL (durable) | Speed + reliability |
| **Metrics/Analysis** | Pandas + Plotly | Interactive, notebook-friendly |
| **Testing** | Pytest + Hypothesis | Property-based testing for edge cases |
| **CI/CD** | GitHub Actions + pre-commit | Industry standard |

### Architecture Sketch

```
┌─────────────────────────────────────────────────────┐
│                   Strategy Layer (Python)             │
│  ┌──────────────────────────────────────────────────┐│
│  │  SignalPipeline:                                  ││
│  │    DataSource → Indicator → Signal → RiskFilter   ││
│  └──────────────────────────────────────────────────┘│
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│              Engine Layer (Rust + Python)             │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐ │
│  │ Backtest │ │  Paper   │ │      Live            │ │
│  │ Engine   │ │  Engine  │ │      Engine          │ │
│  └──────────┘ └──────────┘ └──────────────────────┘ │
│         │            │                │              │
│  ┌──────▼────────────▼────────────────▼──────────┐  │
│  │           Message Bus / Event Loop             │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│           Infrastructure Layer                        │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐ │
│  │ Broker  │ │   Data   │ │ Risk   │ │ Portfolio │ │
│  │ Adapter │ │  Catalog │ │ Module │ │  Tracker  │ │
│  └─────────┘ └──────────┘ └────────┘ └───────────┘ │
│  ┌───────────────────────────────────────────────┐  │
│  │  Persistence (Redis + PostgreSQL + Parquet)    │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Summary of Top 5 Architectural Decisions

| # | Decision | Reference |
|---|----------|-----------|
| 1 | **Hybrid computation**: vectorized indicators → event-driven execution | Freqtrade |
| 2 | **Controller/Executor pattern**: signal logic separate from trade lifecycle | Hummingbot V2 |
| 3 | **Data Catalog**: typed, queryable, Parquet-based historical data | NautilusTrader |
| 4 | **Composable signal pipeline**: data → indicators → signals → risk | Backtrader Lines |
| 5 | **Explicit broker abstraction**: exchange agnostic with simulation modes | LEAN / Hummingbot |
