__all__ = [
    "TickData",
    "BarData",
    "TradeSignalV2",
    "SignalTypeV2",
    "PositionV2",
    "OrderV2",
    "OrderSide",
    "OrderStatus",
    "TradeRecordV2",
    "BacktestConfigV2",
    "BacktestResultV2",
    "validate_signal_dict",
    "convert_legacy_signal",
]

import time
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SignalTypeV2(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class TickData(BaseModel):
    symbol: str
    price: float
    volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    timestamp: float = Field(default_factory=time.time)
    source: str = ""

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"Tick price must be non-negative, got {v}")
        return v


class BarData(BaseModel):
    symbol: str = ""
    date: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    turnover: float = 0.0

    @field_validator("high")
    @classmethod
    def high_gte_low(cls, v: float, info) -> float:
        return v

    @model_validator(mode="after")
    def validate_ohlc(self) -> "BarData":
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) < Low ({self.low})")
        if self.close > self.high or self.close < self.low:
            pass
        return self


class TradeSignalV2(BaseModel):
    signal_type: SignalTypeV2
    strength: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    bar_index: int = Field(default=-1, ge=-1)
    position_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    stop_loss: float = Field(default=0.0, ge=0.0)
    take_profit: float = Field(default=0.0, ge=0.0)
    price: float = Field(default=0.0, ge=0.0)
    timestamp: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def validate_stop_take_profit(self) -> "TradeSignalV2":
        if self.signal_type == SignalTypeV2.BUY:
            if self.stop_loss > 0 and self.price > 0 and self.stop_loss >= self.price:
                raise ValueError(f"Buy stop_loss ({self.stop_loss}) must be < price ({self.price})")
            if self.take_profit > 0 and self.price > 0 and self.take_profit <= self.price:
                raise ValueError(f"Buy take_profit ({self.take_profit}) must be > price ({self.price})")
        elif self.signal_type == SignalTypeV2.SELL:
            if self.stop_loss > 0 and self.price > 0 and self.stop_loss <= self.price:
                raise ValueError(f"Sell stop_loss ({self.stop_loss}) must be > price ({self.price})")
            if self.take_profit > 0 and self.price > 0 and self.take_profit >= self.price:
                raise ValueError(f"Sell take_profit ({self.take_profit}) must be < price ({self.price})")
        return self


class PositionV2(BaseModel):
    symbol: str
    quantity: float = 0.0
    avg_cost: float = Field(default=0.0, ge=0.0)
    market_value: float = Field(default=0.0, ge=0.0)
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0


class OrderV2(BaseModel):
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    price: float = Field(default=0.0, ge=0.0)
    order_type: Literal["market", "limit", "stop"] = "market"
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = Field(default=0.0, ge=0.0)
    filled_price: float = Field(default=0.0, ge=0.0)
    commission: float = Field(default=0.0, ge=0.0)
    timestamp: float = Field(default_factory=time.time)
    order_id: str = ""


class TradeRecordV2(BaseModel):
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    commission: float = Field(default=0.0, ge=0.0)
    slippage: float = Field(default=0.0, ge=0.0)
    pnl: float = 0.0
    timestamp: float = Field(default_factory=time.time)
    trade_id: str = ""


class BacktestConfigV2(BaseModel):
    initial_capital: float = Field(default=1000000.0, gt=0)
    commission_rate: float = Field(default=0.0003, ge=0, le=0.01)
    stamp_tax_rate: float = Field(default=0.001, ge=0, le=0.01)
    slippage_rate: float = Field(default=0.0, ge=0, le=0.01)
    benchmark_symbol: str = ""
    start_date: str = ""
    end_date: str = ""


class BacktestResultV2(BaseModel):
    strategy_name: str
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = Field(default=0.0, le=0)
    win_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    profit_factor: float = 0.0
    total_trades: int = Field(default=0, ge=0)
    win_trades: int = Field(default=0, ge=0)
    loss_trades: int = Field(default=0, ge=0)
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    benchmark_return: float = 0.0
    alpha: float = 0.0
    beta: float = 1.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    sqn: float = 0.0
    config: BacktestConfigV2 | None = None
    trades: list[TradeRecordV2] = []
    equity_curve: list[float] = []
    drawdown_curve: list[float] = []
    dates: list[str] = []


def validate_signal_dict(data: dict[str, Any]) -> TradeSignalV2:
    raw_type = data.get("type", data.get("action", data.get("signal_type", "hold")))
    type_value = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
    return TradeSignalV2(
        signal_type=SignalTypeV2(type_value),
        strength=float(data.get("strength", 0.0)),
        reason=str(data.get("reason", "")),
        bar_index=int(data.get("bar_index", -1)),
        position_pct=float(data.get("position_pct", 0.0)),
        stop_loss=float(data.get("stop_loss", 0.0)),
        take_profit=float(data.get("take_profit", 0.0)),
        price=float(data.get("price", 0.0)),
    )


def convert_legacy_signal(signal: TradeSignalV2) -> dict[str, Any]:
    return {
        "type": signal.signal_type.value,
        "strength": signal.strength,
        "reason": signal.reason,
        "bar_index": signal.bar_index,
        "position_pct": signal.position_pct,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "price": signal.price,
    }
