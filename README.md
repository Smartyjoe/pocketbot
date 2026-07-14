<div align="center">

# 🤖 Pocket Option Trading Bot

**AI-Powered Binary Options Trading Bot with Telegram Interface**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-50%20passing-brightgreen.svg)](#testing)
[![Architecture](https://img.shields.io/badge/Architecture-Clean%20/DDD-orange.svg)](#architecture)

</div>

---

## ✨ Overview

A production-grade trading bot that connects to **Pocket Option** via WebSocket, generates **AI-powered trading signals** using technical indicators and machine learning, and delivers them through an interactive **Telegram bot** — complete with visual signal cards.

### 🎯 Key Features

| Feature | Description |
|---------|-------------|
| **📱 Telegram Interface** | Interactive bot with pair selection, duration picker, and visual signal cards |
| **📊 Technical Analysis** | RSI, MACD, EMA Cross, Bollinger Bands, Stochastic, ROC, ATR — 7 indicators scored |
| **🧠 ML Signal Generation** | LightGBM/XGBoost models trained on historical data with feature engineering |
| **🔌 Live Broker Connection** | Real-time WebSocket connection to Pocket Option via BinaryOptionsToolsV2 |
| **📈 Real-time Market Data** | Live candle streaming with custom time aggregation (1m, 5m, 15m) |
| **🎯 Trade Tracking** | Automatic prediction resolution with win/loss/tie determination |
| **📊 Performance Stats** | Win rate tracking by pair, confidence bucket, and time period |
| **🖼️ Visual Signals** | CALL/PUT signal images sent with every prediction |
| **🔄 Auto-Reconnection** | Exponential backoff reconnection when broker connection drops |
| **🐳 Docker Ready** | PostgreSQL and Redis via Docker Compose |

---

## 🏗️ Architecture

Built with **Clean Architecture** and **Domain-Driven Design** principles:

```
┌─────────────────────────────────────────────────────────┐
│                    INTERFACES LAYER                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Telegram Bot  │  │   REST API   │  │  Notifications │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
├─────────────────────────────────────────────────────────┤
│                  APPLICATION LAYER                       │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │   Trading     │  │   Strategy   │  │   Use Cases    │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
├─────────────────────────────────────────────────────────┤
│                     DOMAIN LAYER                         │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌───────┐ │
│  │ Trade  │ │ Signal │ │ Events │ │  Ports │ │  VOs  │ │
│  └────────┘ └────────┘ └────────┘ └────────┘ └───────┘ │
├─────────────────────────────────────────────────────────┤
│                 INFRASTRUCTURE LAYER                     │
│  ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────────────┐ │
│  │ Broker │ │  ML    │ │ Features │ │   Persistence  │ │
│  └────────┘ └────────┘ └──────────┘ └────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 16+
- Redis 7+
- Docker & Docker Compose (recommended)

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/pocket-option-bot.git
cd pocket-option-bot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Start Infrastructure

```bash
docker compose up -d postgres redis
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

**Required variables:**

| Variable | Description |
|----------|-------------|
| `POCKET_OPTION_SSID` | Session ID from Pocket Option browser cookies |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `DATABASE_URL` | PostgreSQL connection string |

### 4. Run the Bot

```bash
# Start the manual trading bot
python -m apps.manual_trading.main
```

### 5. Start Chatting

Open Telegram and find your bot:

```
/start   - Welcome message
/predict - Get a trading prediction
/stats   - View your win rate & performance
/recent  - See your recent predictions
/help    - Show available commands
```

---

## 📊 Supported Trading Pairs

### Forex (OTC)
| Pair | Display |
|------|---------|
| `EURUSD_otc` | EUR/USD (OTC) |
| `GBPUSD_otc` | GBP/USD (OTC) |
| `USDJPY_otc` | USD/JPY (OTC) |
| `AUDUSD_otc` | AUD/USD (OTC) |
| `USDCAD_otc` | USD/CAD (OTC) |
| `EURGBP_otc` | EUR/GBP (OTC) |
| `EURJPY_otc` | EUR/JPY (OTC) |
| `GBPJPY_otc` | GBP/JPY (OTC) |

### Forex (Standard)
| Pair | Display |
|------|---------|
| `EURUSD` | EUR/USD |
| `GBPUSD` | GBP/USD |
| `USDJPY` | USD/JPY |
| `AUDUSD` | AUD/USD |
| `USDCAD` | USD/CAD |

### Crypto
| Pair | Display |
|------|---------|
| `BTCUSD_otc` | BTC/USD (OTC) |
| `ETHUSD_otc` | ETH/USD (OTC) |

### Timeframes
- **1 minute** (60s) — Quick scalps
- **5 minutes** (300s) — Short-term trades
- **15 minutes** (900s) — Swing trades

---

## 🧠 Signal Generation

The bot analyzes **7 technical indicators** and votes on direction:

| Indicator | Weight | Logic |
|-----------|--------|-------|
| **RSI** | 0.8 | Oversold (<30) → CALL, Overbought (>70) → PUT |
| **MACD** | 0.85 | Bullish crossover → CALL, Bearish crossover → PUT |
| **EMA Cross** | 0.7 | Fast > Slow → CALL, Fast < Slow → PUT |
| **Bollinger %b** | 0.75 | Near lower band → CALL, Near upper band → PUT |
| **Stochastic** | 0.8 | Oversold crossover → CALL, Overbought crossover → PUT |
| **ROC** | 0.6 | Positive momentum → CALL, Negative → PUT |
| **ATR** | — | Volatility filter (no vote, quality gate) |

**Confidence** = Agreement ratio among voting indicators, clamped to [55%, 95%].

---

## 📁 Project Structure

```
├── apps/
│   └── manual_trading/          # Telegram bot application
│       ├── bot.py               # Bot builder & command registration
│       ├── handlers.py          # Telegram command & callback handlers
│       ├── messages.py          # Message formatting (signal, stats, etc.)
│       ├── keyboards.py         # Inline keyboard builders
│       ├── signal_generator.py  # Rule-based signal scoring
│       ├── market_data.py       # Live candle collection from broker
│       ├── trade_tracker.py     # Background prediction resolver
│       ├── database.py          # PostgreSQL prediction store
│       └── models.py            # Pydantic data models
├── domain/                      # Domain layer (entities, events, ports)
│   ├── entities/                # Trade, Signal, Strategy
│   ├── events/                  # Domain events (opened, expired, etc.)
│   ├── ports/                   # Interfaces (repositories, broker)
│   ├── services/                # Risk calculator, signal evaluator
│   └── value_objects/           # Symbol, Direction, Money, etc.
├── infrastructure/              # Infrastructure layer
│   ├── broker/                  # Pocket Option WebSocket client
│   ├── features/                # Feature engine & technical indicators
│   ├── ml/                      # ML models (LightGBM, XGBoost)
│   ├── persistence/             # PostgreSQL, Redis, DuckDB
│   └── research/                # Backtesting & research tools
├── interfaces/                  # Interface layer
│   ├── api/                     # FastAPI REST endpoints
│   └── telegram/                # Telegram bot & notifications
├── tests/                       # Test suite (50+ tests)
├── config/                      # Settings & configuration
├── docker-compose.yml           # PostgreSQL & Redis services
├── requirements.txt             # Python dependencies
└── .env.example                 # Environment template
```

---

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=apps --cov-report=html

# Run specific module tests
python -m pytest tests/apps/manual_trading/ -v
python -m pytest tests/infrastructure/ -v
python -m pytest tests/domain/ -v
```

---

## ⚙️ Configuration

All settings are managed via environment variables with sensible defaults. See `config/settings.py` for the full schema.

### Key Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `POCKET_OPTION_SSID` | — | Browser cookie session ID |
| `TELEGRAM_BOT_TOKEN` | — | Bot token from BotFather |
| `DATABASE_URL` | `postgresql+asyncpg://trader:devpassword@localhost:5432/trading` | PostgreSQL URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `TRADING_DEFAULT_AMOUNT` | `10.0` | Default trade amount (USD) |
| `TRADING_MAX_DAILY_TRADES` | `50` | Daily trade limit |
| `SIGNAL_CONFIDENCE_THRESHOLD` | `0.65` | Min confidence to show signal |

---

## 🔒 Security Notes

- **Never commit `.env`** — it's gitignored by default
- Use `TELEGRAM_ALLOWED_USER_IDS` to restrict bot access
- Set strong database passwords for production
- The bot uses a **demo account** by default (`isDemo: 1`)

---

## 🛠️ Tech Stack

| Category | Technology |
|----------|------------|
| **Language** | Python 3.12 |
| **Framework** | asyncio + python-telegram-bot |
| **Broker** | Pocket Option WebSocket (BinaryOptionsToolsV2) |
| **Database** | PostgreSQL 16 + asyncpg |
| **Cache** | Redis 7 |
| **ML** | LightGBM, XGBoost, scikit-learn |
| **Indicators** | pandas-ta, custom implementation |
| **Validation** | Pydantic v2 |
| **Logging** | structlog |
| **Testing** | pytest + pytest-asyncio |
| **Architecture** | Clean Architecture + DDD |

---

## 📝 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with ❤️ for the trading community**

</div>
