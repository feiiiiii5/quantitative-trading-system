from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AssetClass(StrEnum):
    SPOT = "spot"
    FUTURES = "futures"
    OPTIONS = "options"
    FOREX = "forex"
    CRYPTO = "crypto"


class Timeframe(StrEnum):
    TICK = "tick"
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class MarketType(StrEnum):
    TREND = "trend"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    ARBITRAGE = "arbitrage"
    MARKET_MAKING = "market_making"
    ML_DRIVEN = "ml_driven"


class StopLossType(StrEnum):
    FIXED_PCT = "fixed_pct"
    ATR_MULTIPLE = "atr_multiple"
    TRAILING = "trailing"
    CHANDELIER = "chandelier"
    TIME_BASED = "time_based"
    NONE = "none"


class TakeProfitType(StrEnum):
    FIXED_PCT = "fixed_pct"
    RR_RATIO = "rr_ratio"
    DYNAMIC = "dynamic"
    PARTIAL_EXITS = "partial_exits"
    NONE = "none"


class PositionSizing(StrEnum):
    FIXED = "fixed"
    PERCENT_EQUITY = "percent_equity"
    KELLY = "kelly"
    VOLATILITY_ADJUSTED = "volatility_adjusted"
    ATR_BASED = "atr_based"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LIMIT = "stop_limit"


class SlippageModel(StrEnum):
    NONE = "none"
    FIXED_BPS = "fixed_bps"
    VOLUME_IMPACT = "volume_impact"
    BID_ASK_SPREAD = "bid_ask_spread"


class FillAssumption(StrEnum):
    NEXT_OPEN = "next_open"
    SAME_CLOSE = "same_close"
    VWAP = "vwap"
    BEST_EFFORT = "best_effort"


class SimulationMode(StrEnum):
    VECTORIZED = "vectorized"
    EVENT_DRIVEN = "event_driven"
    WALK_FORWARD = "walk_forward"


class StrategyMeta(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field("1.0.0", max_length=20)
    asset_class: AssetClass = AssetClass.SPOT
    timeframe: Timeframe = Timeframe.D1
    market_type: MarketType = MarketType.TREND
    data_requirements: list[str] = Field(default_factory=lambda: ["OHLCV"])


class ParameterSpec(BaseModel):
    value: Any = None
    type: str = Field("float", pattern=r"^(int|float|bool|enum)$")
    optimize_range: list[float | int | None] = Field(default_factory=lambda: [None, None])
    description: str = ""


class IndicatorSpec(BaseModel):
    name: str
    library: str = Field("custom", pattern=r"^(ta-lib|pandas-ta|custom)$")
    params: dict[str, Any] = Field(default_factory=dict)
    output_columns: list[str] = Field(default_factory=list)


class SignalLogic(BaseModel):
    entry_long: str = ""
    entry_short: str = ""
    exit_long: str = ""
    exit_short: str = ""
    filter_conditions: list[str] = Field(default_factory=list)


class StopLossConfig(BaseModel):
    type: StopLossType = StopLossType.NONE
    value: float | None = None


class PartialExit(BaseModel):
    pct: float = Field(..., gt=0, le=100)
    rr_trigger: float = Field(..., gt=0)


class TakeProfitConfig(BaseModel):
    type: TakeProfitType = TakeProfitType.NONE
    value: float | None = None
    partial_exits: list[PartialExit] = Field(default_factory=list)


class RiskManagement(BaseModel):
    position_sizing: PositionSizing = PositionSizing.PERCENT_EQUITY
    position_size_value: float | None = None
    stop_loss: StopLossConfig = Field(default_factory=StopLossConfig)
    take_profit: TakeProfitConfig = Field(default_factory=TakeProfitConfig)
    max_open_positions: int | None = Field(None, ge=1)
    max_portfolio_risk_pct: float | None = Field(None, ge=0, le=100)
    max_correlated_positions: int | None = Field(None, ge=1)
    daily_loss_limit_pct: float | None = Field(None, ge=0, le=100)
    leverage: float = Field(1.0, ge=1.0, le=100.0)


class CommissionConfig(BaseModel):
    maker_bps: float = Field(0, ge=0)
    taker_bps: float = Field(0, ge=0)
    min_fee: float = Field(0, ge=0)


class ExecutionModel(BaseModel):
    order_type: OrderType = OrderType.MARKET
    slippage_model: SlippageModel = SlippageModel.NONE
    commission: CommissionConfig = Field(default_factory=CommissionConfig)
    latency_ms: float = Field(0, ge=0)
    fill_assumption: FillAssumption = FillAssumption.NEXT_OPEN


class StrategyDefinition(BaseModel):
    strategy_meta: StrategyMeta
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    indicators: list[IndicatorSpec] = Field(default_factory=list)
    signal_logic: SignalLogic = Field(default_factory=SignalLogic)
    risk_management: RiskManagement = Field(default_factory=RiskManagement)
    execution_model: ExecutionModel = Field(default_factory=ExecutionModel)

    def min_bars_required(self) -> int:
        lookback = 0
        for ind in self.indicators:
            for v in ind.params.values():
                if isinstance(v, (int, float)) and v > lookback:
                    lookback = int(v)
        for p in self.parameters.values():
            if isinstance(p.value, (int, float)) and p.value and p.value > lookback:
                lookback = max(lookback, int(p.value))
        return max(lookback * 3, 30)

    def summary_card(self) -> str:
        meta = self.strategy_meta
        n_params = len(self.parameters)
        min_bars = self.min_bars_required()
        regime = {
            MarketType.TREND: "趋势行情",
            MarketType.MEAN_REVERSION: "震荡行情",
            MarketType.MOMENTUM: "动量行情",
            MarketType.ARBITRAGE: "套利机会",
            MarketType.MARKET_MAKING: "高流动性窄价差",
            MarketType.ML_DRIVEN: "数据驱动",
        }.get(meta.market_type, "未知")
        return (
            f"╔══════════════════════════════════════════╗\n"
            f"║  Strategy: {meta.name:<28s}║\n"
            f"║  Type: {meta.market_type.value:<34s}║\n"
            f"║  Timeframe: {meta.timeframe.value} | Asset: {meta.asset_class.value:<13s}║\n"
            f"║  Parameters: {n_params:<28d}║\n"
            f"║  Min Bars Required: {min_bars:<20d}║\n"
            f"║  Estimated Edge: {regime:<22s}║\n"
            f"╚══════════════════════════════════════════╝"
        )
