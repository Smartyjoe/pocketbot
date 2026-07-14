# Architectural Analysis: Quantitative Research Platform in Python

## 1. Clean Architecture + DDD in Python

### Layers

```
domain/          # Pure Python, zero dependencies on infrastructure
    entities/    # Mutable objects with identity (UUID)
    value_objects/  # Immutable, self-validating
    aggregates/  # Root entity + invariant enforcement
    events/      # Domain events (pydantic BaseModel)
    repositories/  # Protocols only
    services/    # Stateless domain services

application/    # Orchestration, no infrastructure imports
    use_cases/  # Single-responsibility callable classes
    ports/      # Input/output ports (interfaces)
    dto/        # Data transfer objects

infrastructure/  # Adapters
    db/          # PostgreSQL via asyncpg/SQLAlchemy
    cache/       # Redis adapters
    bus/         # Event bus implementations
    external/    # Broker APIs, data providers

interfaces/      # Entry points
    api/         # FastAPI routes
    cli/         # Click/Typer commands
    consumers/   # Message queue consumers
```

### DDD Patterns in Python

```python
# Value Object (immutable)
from pydantic import BaseModel, ConfigDict

class Money(BaseModel):
    model_config = ConfigDict(frozen=True)
    amount: Decimal
    currency: str

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise CurrencyMismatchError(...)
        return Money(amount=self.amount + other.amount, currency=self.currency)

# Entity (mutable, identity via UUID)
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

class Order(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    side: Side  # enum
    quantity: Decimal
    status: OrderStatus = OrderStatus.PENDING

    def fill(self, fill_qty: Decimal, fill_price: Decimal) -> OrderFilled:
        self.status = OrderStatus.FILLED
        return OrderFilled(order_id=self.id, fill_qty=fill_qty, fill_price=fill_price)

# Domain Event
class OrderFilled(BaseModel):
    model_config = ConfigDict(frozen=True)
    order_id: UUID
    fill_qty: Decimal
    fill_price: Decimal
    occurred_at: datetime = Field(default_factory=datetime.utcnow)

# Repository Protocol
from typing import Protocol

class OrderRepository(Protocol):
    async def save(self, order: Order) -> None: ...
    async def get(self, order_id: UUID) -> Order | None: ...
    async def get_by_symbol(self, symbol: str) -> list[Order]: ...

# Aggregate Root
class Portfolio(BaseModel):
    id: UUID
    positions: dict[str, Position]
    cash: Money

    def apply_trade(self, trade: Trade) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        if trade.side == Side.BUY:
            position = self.positions.get(trade.symbol)
            if position:
                position = position.add(trade.quantity, trade.price)
            else:
                position = Position(symbol=trade.symbol, quantity=trade.quantity)
            self.positions[trade.symbol] = position
            self.cash -= trade.total_cost
        events.append(PositionUpdated(portfolio_id=self.id, ...))
        return events
```

### Dependency Inversion

- **Domain layer** defines `Protocol` interfaces for repositories, event bus, clock
- **Application layer** depends only on those Protocols
- **Infrastructure layer** implements the Protocols
- Wiring: FastAPI `Depends` or a factory function at composition root

### Libraries

| Library | Use | Why |
|---------|-----|-----|
| `pydantic v2` | Models, validation, serialization | Fast, native Python, serializes to/from dict/JSON |
| `typing.Protocol` | Interface definitions | Structural subtyping, zero runtime overhead |
| `result` | Railway-oriented error handling | `Result[T, E]` instead of exceptions for expected failures |
| `returns` | Monads (Maybe, Result, IO, Reader) | Pure functional pipelines, composable error handling |

### Pitfalls to Avoid

- **Anemic domain model**: Don't put all logic in services; entities should enforce their own invariants
- **Java-itis**: Don't create interfaces for everything. Use Protocol only when you need polymorphism
- **Validation leaking**: Keep `pydantic` validation at boundaries; domain objects should be valid by construction
- **Over-layering**: Five layers aren't cleaner than three. Start thin, extract when you feel the pain
- **DI framework abuse**: Avoid `dependency_injector` (too much magic). Use FastAPI `Depends` or manual wiring

---

## 2. Event-Driven Architecture

### Patterns

**Event Bus** (in-process, decouples within same process):

```python
from pydantic import BaseModel
from collections import defaultdict
from typing import Callable, Type

Handler = Callable[[BaseModel], Awaitable[None]]

class EventBus:
    def __init__(self):
        self._handlers: dict[type[BaseModel], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[BaseModel], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: BaseModel) -> None:
        for handler in self._handlers.get(type(event), []):
            await handler(event)
```

**Event Sourcing**:
- Store events as append-only log (PostgreSQL table `events` or Kafka topic)
- Rebuild aggregate state by replaying events (`aggregate.apply(event)`)
- Enables full audit trail, time-travel debugging, backtesting

**CQRS**:
- **Commands**: Mutate state, return void. `CreateOrder(symbol="BTCUSD", qty=1.0)`
- **Queries**: Read from optimized materialized views, return data
- Write side uses domain model + events; read side uses flat tables/DuckDB/materialized views
- Eventually consistent: command → event → read model update

### When to Use Event-Driven vs Direct Calls

| Use Event-Driven | Use Direct Calls |
|----------------|-----------------|
| Cross-domain concerns (trading → risk → accounting) | Within the same aggregate |
| Multiple consumers need same data | Simple CRUD operations |
| Need audit trail / replay | Strong consistency required |
| Temporal decoupling (can happen later) | Request-response latency critical |

### Decoupling Example in Trading

```
SignalGenerator → (SignalGenerated) → RiskManager → (RiskChecked) → OrderRouter → (OrderSubmitted)
      ↑                                                                              ↓
      └──────────────────── (ExecutionReport) ←────────── Broker ←── OrderPlaced ←──┘
                                         ↓
                              PositionManager → (PositionUpdated) → PnL calcs
```

Each arrow is an event. Each component can be replaced, tested, or scaled independently.

---

## 3. Async Python

### Core Patterns

**Structured Concurrency (Python 3.11+)**:

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(market_data_feed())
    tg.create_task(strategy_runner())
    tg.create_task(order_manager())
# Tasks are cancelled if any task fails, or on scope exit
```

**Task Management**:
- Use `asyncio.TaskGroup` (3.11+) or `trio.Nursery` over bare `asyncio.create_task`
- Never fire tasks without tracking them — leads to orphaned tasks and memory leaks
- Graceful shutdown: cancel all tasks, drain queues, flush logs

**Queue Patterns**:

```python
# Producer-consumer pipeline
class DataPipeline:
    def __init__(self):
        self.raw_data: asyncio.Queue[MarketData] = asyncio.Queue(maxsize=1000)
        self.processed: asyncio.Queue[ProcessedData] = asyncio.Queue(maxsize=1000)
        self.signals: asyncio.Queue[Signal] = asyncio.Queue(maxsize=100)

    async def ingest(self, source): ...
    async def process(self): ...
    async def generate_signals(self): ...
```

**Rate Limiting**:

```python
# Token bucket
class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()

    async def acquire(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens < 1:
            await asyncio.sleep((1 - self.tokens) / self.rate)
            self.tokens = 0
        else:
            self.tokens -= 1
```

**Connection Pooling**:

```python
# asyncpg pool
pool = await asyncpg.create_pool(dsn=DSN, min_size=5, max_size=20)

# async with pool.acquire() as conn:
#     await conn.fetch("SELECT * FROM signals WHERE ...")

# Redis pool (built-in)
redis = await redis.asyncio.Redis(connection_pool=BlockingConnectionPool(max_connections=10))
```

**Async Context Managers**:

```python
class DatabaseSession:
    async def __aenter__(self):
        self.conn = await pool.acquire()
        return self.conn

    async def __aexit__(self, *exc):
        await pool.release(self.conn)
```

### Libraries

| Library | Use | Notes |
|---------|-----|-------|
| `anyio` | Cross-backend async | Write once for asyncio+trio. `TaskGroup`, semaphores, files, networking |
| `aiometer` | Rate limiting + concurrency | Built on anyio, token-bucket + semaphore |
| `asyncpg` | PostgreSQL driver | 3x faster than aiopg, pure async |
| `aiohttp` | HTTP client/server | Connection pooling, session reuse |
| `httpx` | HTTP client | Async API, better DX, but heavier than aiohttp |

### `trio` vs `asyncio`

- **trio**: Stronger structured concurrency, cancel scopes, no footguns. Smaller ecosystem.
- **asyncio**: Larger ecosystem, standard library. The safe bet.
- **Best practice**: Use `anyio` as an abstraction layer. Write to `anyio` APIs, swap backend if needed.

---

## 4. FastAPI

### Project Structure

```
api/
├── main.py              # FastAPI app creation, middleware, lifespan
├── deps.py              # Dependency injection (get_db, get_current_user, etc.)
├── v1/
│   ├── __init__.py      # APIRouter aggregator
│   ├── auth.py          # POST /login, POST /register
│   ├── orders.py        # CRUD /orders
│   ├── signals.py       # GET /signals
│   ├── portfolio.py     # GET /portfolio, POST /rebalance
│   └── ws.py            # WebSocket /ws/market-data
├── middleware.py         # CORS, request ID, timing, logging
└── exceptions.py        # Custom exception handlers
```

### Dependency Injection

```python
# deps.py
async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    async with pool.acquire() as conn:
        yield conn

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    ...

async def get_event_bus() -> EventBus:
    return app.state.event_bus

# routes/orders.py
@router.post("/orders")
async def create_order(
    order: OrderCreate,
    db: asyncpg.Connection = Depends(get_db),
    bus: EventBus = Depends(get_event_bus),
    user: User = Depends(get_current_user),
):
    ...
```

### Background Tasks

```python
# Lightweight: FastAPI BackgroundTasks
@router.post("/orders")
async def create_order(
    order: OrderCreate,
    background_tasks: BackgroundTasks,
):
    result = await order_service.create(order)
    background_tasks.add_task(notify_telegram, result)
    return result

# Heavy computation: separate worker (ARQ / Celery)
# FastAPI publishes a job; worker executes; result stored in Redis
```

### WebSocket

```python
class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, symbol: str, ws: WebSocket):
        await ws.accept()
        self.active[symbol] = ws

    def disconnect(self, symbol: str):
        self.active.pop(symbol, None)

    async def broadcast(self, symbol: str, data: dict):
        if ws := self.active.get(symbol):
            try:
                await ws.send_json(data)
            except WebSocketDisconnect:
                self.disconnect(symbol)

@router.websocket("/ws/{symbol}")
async def market_data_ws(websocket: WebSocket, symbol: str, manager: ConnectionManager = Depends()):
    await manager.connect(symbol, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Handle client messages (subscribe, unsubscribe)
    except WebSocketDisconnect:
        manager.disconnect(symbol)
```

### API Versioning

```python
# URL-based (preferred)
app.mount("/v1", v1_router)
app.mount("/v2", v2_router)

# Header-based (for internal APIs)
@router.get("/orders")
async def get_orders(version: str = Header("v1")):
    if version == "v2":
        return await order_service_v2()
    return await order_service_v1()
```

### Middleware Pattern

```python
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid4())
    with structlog.contextvars.bound_contextvars(request_id=request_id):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

---

## 5. Data Stack

### DuckDB vs PostgreSQL

| Concern | DuckDB | PostgreSQL |
|---------|--------|------------|
| **Use case** | Analytics, backtesting, ad-hoc queries | Transactional source of truth |
| **Concurrency** | Single-user (in-process) | Multi-user, ACID |
| **Data format** | Parquet, CSV, in-memory | Table-oriented |
| **Performance** | Columnar, vectorized | Row-oriented, MVCC |
| **Query type** | OLAP (aggregations, window functions) | OLTP (point lookups, inserts) |
| **Network** | Embedded, no server | Server, TCP connections |

**Rule of thumb**: DuckDB for research/backtesting. PostgreSQL for live system state.

### PostgreSQL Schema Patterns

```python
# Partitioned trades table
CREATE TABLE trades (
    id UUID NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL,
    quantity NUMERIC(20, 8) NOT NULL,
    price NUMERIC(20, 8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    metadata JSONB,
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

CREATE TABLE trades_2026_q1 PARTITION OF trades
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');

# Signals table with composite index
CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    signal_type VARCHAR(50) NOT NULL,
    strength NUMERIC(5, 2),
    parameters JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_signals_lookup ON signals (symbol, timestamp DESC);

# Event store (event sourcing)
CREATE TABLE domain_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id UUID NOT NULL,
    aggregate_type VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    version INTEGER NOT NULL,
    data JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    UNIQUE (aggregate_id, version)
);
```

### Redis Strategies

| Pattern | Implementation | Use Case |
|---------|---------------|----------|
| Cache-aside | GET/SET with TTL | Cached indicator values, reference data |
| Pub/Sub | PUBLISH/SUBSCRIBE | Real-time signal distribution |
| Rate limiting | INCR + EXPIRE or sorted sets | API rate limits per user/IP |
| Session | SETEX with session ID | User sessions for Flask/FastAPI |
| Leaderboard | ZADD/ZRANGE by score | Strategy rankings |
| Distributed lock | SET NX EX | Prevent duplicate trade execution |

### TimescaleDB: Worth It?

**Yes, when:**
- Tick-level data (millions of rows/second)
- Continuous aggregates (auto-refreshed 1m/1h/1d candles)
- Data retention policies (auto-drop raw ticks after N days, keep aggregated forever)
- Native compression (90%+ reduction on tick data)

**Not worth it when:**
- Only storing daily/1m OHLCV (plain PostgreSQL works fine)
- Simple partition pruning is sufficient (partition by month)
- No need for continuous aggregates
- < 10M rows

**Alternative**: Plain PostgreSQL with time-based partitioning + materialized views refreshed via pg_cron.

---

## 6. Scientific Python Stack

### numpy + numba

```python
import numpy as np
from numba import njit

@njit(cache=True)
def rsi(prices: np.ndarray, window: int = 14) -> np.ndarray:
    deltas = np.diff(prices)
    gains = np.maximum(deltas, 0)
    losses = np.abs(np.minimum(deltas, 0))
    avg_gain = np.zeros_like(prices)
    avg_loss = np.zeros_like(prices)
    avg_gain[window] = gains[:window].mean()
    avg_loss[window] = losses[:window].mean()
    for i in range(window + 1, len(prices)):
        avg_gain[i] = (avg_gain[i - 1] * (window - 1) + gains[i - 1]) / window
        avg_loss[i] = (avg_loss[i - 1] * (window - 1) + losses[i - 1]) / window
    rs = avg_gain / np.maximum(avg_loss, 1e-10)
    return 100 - (100 / (1 + rs))
```

- **numpy**: Foundation for all computation. Use contiguous arrays, avoid Python loops.
- **numba**: `@njit` on tight computational loops. ~50-200x speedup. Works with numpy arrays, not pandas DataFrames.
- **Avoid**: `@jit` (use `@njit` for better errors), calling numba functions with Python objects, using pandas in numba.

### pandas vs polars

| Concern | pandas | polars |
|---------|--------|--------|
| **API** | Mature, many books/blog posts | Newer, but intuitive |
| **Performance** | Single-threaded by default | Multi-core, parallel by default |
| **Memory** | Copies on modification | Copy-on-write, zero-copy where possible |
| **Large datasets** | Slow, high memory | Streaming, memory-efficient |
| **Index** | Rich index operations | No index (explicit column) |
| **Timezones** | Good support | Weaker timezone handling |
| **GroupBy** | Can be slow | Highly optimized |

**Verdict for trading**: Use **polars** for backtesting data pipelines (loading, filtering, aggregating 10M+ rows). Use **pandas** when you need complex index-based operations (panel data, reindexing, timeseries alignment). Hybrid is fine — convert between them.

### xarray

```python
import xarray as xr

# N-dimensional labeled array for volatility surface
ds = xr.Dataset(
    {"implied_vol": (["strike", "expiry", "time"], data)},
    coords={
        "strike": strikes,
        "expiry": expirations,
        "time": timestamps,
    }
)

# Select surface slice
surface = ds.sel(time="2026-01-15", method="nearest")
atm_slice = surface.sel(strike=100, method="nearest")
```

Use for: volatility surfaces, correlation matrices, factor research, multi-asset timeseries.

### ML Integration

```python
# Feature engineering pipeline
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import xgboost as xgb

pipeline = Pipeline([
    ("scaler", StandardScaler()),
    ("pca", PCA(n_components=20)),
    ("xgb", xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.01,
        early_stopping_rounds=10,
    )),
])

# Train
pipeline.fit(X_train, y_train)

# Model registry (MLflow)
with mlflow.start_run():
    mlflow.log_params(params)
    mlflow.sklearn.log_model(pipeline, "model")
    mlflow.log_metric("sharpe", sharpe_ratio)

# Inference via ONNX
import onnxruntime as ort
session = ort.InferenceSession("model.onnx")
predictions = session.run(None, {"input": features})
```

**Pattern**: Train offline (polars + xgboost/LightGBM), export to ONNX, serve inference in asyncio pipeline.

---

## 7. Configuration Management

### pydantic-settings

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, PostgresDsn, RedisDsn

class DBSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env")
    host: str = "localhost"
    port: int = 5432
    user: str
    password: SecretStr
    database: str
    pool_min: int = 5
    pool_max: int = 20

    @property
    def dsn(self) -> PostgresDsn:
        return f"postgresql://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.database}"

class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")
    host: str = "localhost"
    port: int = 6379
    password: SecretStr | None = None

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    debug: bool = False
    secret_key: SecretStr
    db: DBSettings = DBSettings()
    redis: RedisSettings = RedisSettings()
    log_level: str = "INFO"

settings = AppSettings()  # Singleton, fast everywhere
```

### YAML Config with Pydantic

```python
class StrategyConfig(BaseModel):
    name: str
    symbols: list[str]
    params: dict[str, Any]
    schedule: str  # cron expression

class TradingConfig(BaseModel):
    strategies: list[StrategyConfig]
    max_position_size: Decimal
    max_leverage: Decimal
    allowed_exchanges: list[str]

# Load and validate
with open("config/strategies.yaml") as f:
    config = TradingConfig.model_validate(yaml.safe_load(f))
```

### Twelve-Factor App

1. **Codebase**: One repo per deployable, or monorepo with packages
2. **Dependencies**: Explicit, pinned, in lockfile
3. **Config**: Environment variables (never code)
4. **Backing services**: Treat as attached resources (DSN config)
5. **Build, release, run**: Separate stages (Docker multi-stage)
6. **Processes**: Stateless, share-nothing
7. **Port binding**: Self-contained (FastAPI serves HTTP)
8. **Concurrency**: Scale via processes (not threads)
9. **Disposability**: Fast startup, graceful shutdown (SIGTERM)
10. **Dev/prod parity**: Same stack locally and in prod
11. **Logs**: Event streams (stdout, structured JSON)
12. **Admin processes**: One-off scripts in same env

### Secrets Management

| Environment | Method |
|-------------|--------|
| Local dev | `.env` file (gitignored) |
| Docker | Docker secrets (`/run/secrets/*`) |
| K8s | Kubernetes Secrets → env vars |
| Production | HashiCorp Vault / AWS Secrets Manager |

**Never**: Commit secrets, use `str` instead of `SecretStr`/`SecretBytes`, log configs.

---

## 8. Monitoring and Observability

### Structured Logging with structlog

```python
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()

# Usage
logger.info("order.submitted", order_id=order.id, symbol="BTCUSD", qty=1.0)

# Context binding
log = logger.bind(request_id=request_id)
log.info("processing.start")
```

**Why structlog over loguru**: JSON output by default, context binding without thread-locals, `structlog.contextvars` works with asyncio, battle-proven at scale.

### Metrics with Prometheus

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

orders_submitted = Counter("orders_submitted_total", "Total orders", ["symbol", "side"])
signal_latency = Histogram("signal_computation_seconds", "Signal computation latency",
    buckets=[.0001, .001, .01, .05, .1, .5, 1.0])
active_positions = Gauge("active_positions", "Current open positions", ["symbol"])

# FastAPI middleware
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    request_duration.observe(time.perf_counter() - start)
    return response

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

### OpenTelemetry

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

tracer = trace.get_tracer(__name__)

@app.on_event("startup")
async def setup_tracing():
    exporter = OTLPSpanExporter(endpoint="http://jaeger:4317")
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)

# Custom spans
async def compute_signal(symbol: str):
    with tracer.start_as_current_span("compute_signal") as span:
        span.set_attribute("symbol", symbol)
        result = await indicator_service.calculate(symbol)
        return result
```

### Health Checks

```python
@app.get("/health")
async def health(db: asyncpg.Connection = Depends(get_db)):
    """Liveness: is the process alive and can connect to DB?"""
    try:
        await db.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "db": str(e)}
        )

@app.get("/ready")
async def ready():
    """Readiness: are data pipelines loaded and caches warm?"""
    if not app.state.pipelines_loaded:
        return JSONResponse(status_code=503, content={"status": "not ready"})
    return {"status": "ready"}
```

### Log Aggregation

```
App (JSON stdout) → Filebeat/Vector → Loki → Grafana
                                   → Elasticsearch → Kibana
```

**Pattern**: App always writes structured JSON to stdout. Log shipper (Vector is lightweight, fast) sends to centralized store. Grafana for dashboards and alerts.

---

## 9. Docker and Deployment

### Multi-Stage Docker Build

```dockerfile
# Stage 1: Build dependencies
FROM python:3.12-slim AS builder
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-deps -r pyproject.toml

# Stage 2: Runtime
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app/ /app/
WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose for Local Dev

```yaml
version: "3.9"
services:
  app:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [db, redis]
    volumes: ["./app:/app"]  # hot-reload for dev

  worker:
    build: .
    command: python -m workers.signal_worker
    env_file: .env
    depends_on: [db, redis]

  db:
    image: postgres:16
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data", "./init.sql:/docker-entrypoint-initdb.d/init.sql"]
    environment:
      POSTGRES_DB: trading
      POSTGRES_USER: trader
      POSTGRES_PASSWORD: devpassword

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports: ["16686:16686", "4317:4317"]

  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]

volumes:
  pgdata:
```

### CI/CD Pipeline (GitHub Actions)

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv lock --check
      - run: uvx ruff check .
      - run: uvx ruff format --check .
      - run: uvx pyright .

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: test }
      redis:
        image: redis:7-alpine
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run pytest tests/unit -v
      - run: uv run pytest tests/integration -v --db-url=${{ secrets.TEST_DB_URL }}

  build:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/org/trading-platform:${{ github.sha }}
```

### Testing Strategy

| Level | Scope | Speed | What to test |
|-------|-------|-------|-------------|
| **Unit** | Single function/class | ms | Domain logic, indicators, validation |
| **Integration** | Module + dependencies | s | DB queries, Redis cache, event bus |
| **E2E** | Full pipeline | min | Signal → Risk → Order → Fill cycle |

```python
# Unit test (pure function)
def test_rsi_calculation():
    prices = np.array([44, 44.3, 44.5, ...])
    result = rsi(prices, window=14)
    assert np.isclose(result[-1], 62.5, atol=0.1)

# Integration test (with testcontainers)
@pytest.mark.integration
async def test_save_and_load_order(postgres: asyncpg.Pool):
    order = Order(symbol="BTCUSD", ...)
    repo = PostgresOrderRepository(postgres)
    await repo.save(order)
    loaded = await repo.get(order.id)
    assert loaded == order
```

**Avoid**: Mocking databases unless necessary. Use `testcontainers-postgres` / `testcontainers-redis` instead.

---

## 10. Dependency Management

### Library Comparison

| Tool | Speed | Lockfile | Workspaces | Python version mgmt | Notes |
|------|-------|----------|------------|-------------------|-------|
| **uv** | ⚡ Fastest | uv.lock | Yes | Yes (via `uv python install`) | Rust-based, pip-compatible, recommended default |
| **poetry** | 🐢 Slow resolution | poetry.lock | Yes (1.8+) | No | Mature, good UX, but slow |
| **pip-tools** | ⚡ Fast | requirements.txt | Manual | No | Minimal, transparent, no build system |
| **pixi** | ⚡ Fast | pixi.lock | Yes | Yes (conda-based) | Best for mixed C++/Python stacks |

### Recommended: `uv`

```toml
# pyproject.toml
[project]
name = "trading-platform"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "fastapi>=0.110",
    "asyncpg>=0.29",
    "polars>=1.0",
    "numpy>=2.0",
    "structlog>=24.0",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.4", "pyright>=1.1"]
ml = ["xgboost>=2.0", "scikit-learn>=1.5"]
backtest = ["duckdb>=1.0", "numba>=0.60"]
```

```bash
# Commands
uv sync                # Install all deps
uv sync --group dev    # Install dev deps
uv add asyncpg         # Add dependency
uv lock                # Update lockfile
uv run pytest          # Run command in venv
```

### Workspaces/Monorepo

```
trading-platform/
├── pyproject.toml          # Root workspace config
├── uv.lock
├── packages/
│   ├── domain/             # Domain entities, value objects
│   │   └── pyproject.toml
│   ├── infrastructure/     # DB, cache, broker adapters
│   │   └── pyproject.toml
│   ├── api/                # FastAPI interfaces
│   │   └── pyproject.toml
│   └── strategies/         # Trading strategies
│       └── pyproject.toml
├── tests/
└── config/
```

**Avoid**: Pinning versions without upper bounds (`numpy>=1.20,<3.0`), not committing lockfile, mixing conda and pip, using `pip install` instead of `uv sync`.

---

## Summary: Recommended Stack

| Concern | Library |
|---------|---------|
| **Domain modeling** | `pydantic`, `typing.Protocol` |
| **API** | `FastAPI` + `uvicorn` |
| **Async** | `anyio`, `asyncpg`, `httpx` |
| **DB** | `PostgreSQL` (source of truth), `DuckDB` (analytics) |
| **Cache / real-time** | `Redis` |
| **Data science** | `numpy`, `numba`, `polars` |
| **ML** | `xgboost`, `scikit-learn`, `MLflow`, `ONNX` |
| **Config** | `pydantic-settings` |
| **Logging** | `structlog` |
| **Metrics** | `prometheus_client` |
| **Tracing** | `opentelemetry` |
| **CI** | `GitHub Actions` |
| **Container** | `Docker` multi-stage |
| **Deps** | `uv` |

---

## Anti-Patterns to Avoid

| Anti-Pattern | Instead |
|-------------|---------|
| One giant monolith | Clean architecture layers, separate packages |
| Business logic in route handlers | Use case classes in application layer |
| Pandas in live trading loops | numpy + numba for real-time, polars for batch |
| Mocking databases in tests | testcontainers with real PostgreSQL/Redis |
| Synchronous blocking calls in async | Always use async libraries (asyncpg, httpx) |
| No type hints | Every function typed, strict mypy/pyright |
| Configuration in code | Environment variables + pydantic-settings |
| Not versioning APIs | URL-based versioning from day one |
| Pickle for ML models | ONNX or MLflow model registry |
| Ignoring graceful shutdown | Signal handlers, TaskGroup cancellation |
