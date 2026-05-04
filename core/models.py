from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class MarketRegimeType(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    SIDEWAYS = "sideways"
    UNKNOWN = "unknown"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class TradeSignal:
    signal_type: SignalType
    strength: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class KlineBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open


@dataclass(frozen=True)
class Position:
    symbol: str
    entry_price: float
    shares: int
    entry_date: str = ""
    stop_loss: float = 0.0
    take_profit: float = 0.0

    @property
    def cost(self) -> float:
        return self.entry_price * self.shares

    @property
    def risk_per_share(self) -> float:
        if self.stop_loss > 0:
            return self.entry_price - self.stop_loss
        return 0.0


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: float
    positions: Dict[str, Position] = field(default_factory=dict)
    timestamp: float = 0.0

    @property
    def total_position_value(self) -> float:
        return sum(p.entry_price * p.shares for p in self.positions.values())

    @property
    def total_value(self) -> float:
        return self.cash + self.total_position_value

    @property
    def position_count(self) -> int:
        return len(self.positions)


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_trade_return: float = 0.0
    calmar_ratio: float = 0.0


@dataclass(frozen=True)
class PortfolioRiskMetrics:
    """组合风险指标（与risk_monitor.RiskMetrics互补）"""
    var_95: float = 0.0
    cvar_95: float = 0.0
    daily_volatility: float = 0.0
    annual_volatility: float = 0.0
    beta: float = 0.0
    concentration: Dict[str, float] = field(default_factory=dict)
    max_concentration: float = 0.0


@dataclass(frozen=True)
class MarketDataPoint:
    symbol: str
    price: float
    change_pct: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    timestamp: float = 0.0
    market: str = ""

    @property
    def is_valid(self) -> bool:
        return self.price > 0 and self.symbol != ""


@dataclass(frozen=True)
class StrategyPerformance:
    name: str
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    avg_pnl: float = 0.0


@dataclass(frozen=True)
class WalkForwardSplitResult:
    split_index: int
    train: BacktestMetrics = field(default_factory=BacktestMetrics)
    validation: BacktestMetrics = field(default_factory=BacktestMetrics)
    test: BacktestMetrics = field(default_factory=BacktestMetrics)
    overfitting_score: float = 0.0


@dataclass(frozen=True)
class CorrelationResult:
    symbol_a: str
    symbol_b: str
    correlation: float
    is_significant: bool = False

    @property
    def is_highly_correlated(self) -> bool:
        return abs(self.correlation) > 0.7
