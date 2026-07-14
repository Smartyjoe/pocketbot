from fastapi import APIRouter
from pydantic import BaseModel
from decimal import Decimal

router = APIRouter()


class TradeRequest(BaseModel):
    symbol: str
    direction: str
    amount: Decimal
    duration_seconds: int = 60


class TradeResponse(BaseModel):
    trade_id: str
    symbol: str
    direction: str
    amount: str
    entry_price: str
    status: str


class BalanceResponse(BaseModel):
    balance: str


class HealthResponse(BaseModel):
    status: str
    broker: str


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", broker="pocket_option")


@router.get("/balance", response_model=BalanceResponse)
async def get_balance():
    return BalanceResponse(balance="0.00")


@router.post("/trades", response_model=TradeResponse)
async def open_trade(req: TradeRequest):
    return TradeResponse(
        trade_id="pending",
        symbol=req.symbol,
        direction=req.direction,
        amount=str(req.amount),
        entry_price="0.00",
        status="pending",
    )


@router.get("/trades/open")
async def list_open_trades():
    return {"trades": []}


@router.get("/trades/history")
async def trade_history(limit: int = 20):
    return {"trades": []}
