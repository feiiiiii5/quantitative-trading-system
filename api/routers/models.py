from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)


class BuyOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, pattern=r'^[0-9a-zA-Z]{1,10}$')
    price: float = Field(..., gt=0, description="委托价格")
    shares: int = Field(..., gt=0, le=1000000, description="买入数量")
    name: str = Field("", max_length=20)
    market: str = Field("A", pattern=r'^[AHU]$')

    @field_validator('shares')
    @classmethod
    def validate_shares(cls, v):
        if v % 100 != 0:
            raise ValueError('A股买入数量必须为100的整数倍')
        return v


class SellOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, pattern=r'^[0-9a-zA-Z]{1,10}$')
    price: float = Field(..., gt=0, description="委托价格")
    shares: int = Field(..., gt=0, le=1000000, description="卖出数量")


class BacktestRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    strategy_type: str = Field("adaptive", max_length=50, pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    start_date: str = Field("2024-01-01", pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field("2025-12-31", pattern=r'^\d{4}-\d{2}-\d{2}$')
    initial_capital: float = Field(1000000, gt=0, le=100000000)


class BacktestOptimizeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    strategy_name: str = Field("ma_cross", max_length=50, pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    start_date: str = Field("2023-01-01", pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field("2024-12-31", pattern=r'^\d{4}-\d{2}-\d{2}$')
    metric: str = Field("sharpe_ratio", max_length=30)
    max_combinations: int = Field(100, gt=0, le=1000)


class WatchlistAddRemoveRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')


class WatchlistReorderRequest(BaseModel):
    symbols: str = Field(..., min_length=1, max_length=500)


class AlertAddRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    alert_type: str = Field(..., pattern=r'^(price_above|price_below|change_pct_above|change_pct_below|volume_above)$')
    value: float = Field(..., gt=0, lt=1e8)


class AlertRemoveRequest(BaseModel):
    alert_id: str = Field(..., min_length=1, max_length=50)


class TradingBuyRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    name: str = Field("", max_length=20)
    market: str = Field("", max_length=2)
    price: float = Field(..., gt=0)
    shares: int = Field(..., gt=0, le=1000000)
    stop_loss: float = Field(0, ge=0)
    take_profit: float = Field(0, ge=0)
    strategy: str = Field("manual", max_length=50)


class TradingSellRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    price: float = Field(..., gt=0)
    shares: int | None = Field(None, gt=0, le=1000000)
    reason: str = Field("manual", max_length=50)


class ConfigSetRequest(BaseModel):
    value: str = Field(..., max_length=10000)


class AlphaEvolveRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    max_iterations: int = Field(3, gt=0, le=20)
    period: str = Field("1y", max_length=5)


class AuditStrategyRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    strategy_name: str = Field("adaptive", max_length=50, pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    period: str = Field("1y", max_length=5)


class WatchlistAddRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')


class PriceAlertRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    target_price: float = Field(..., gt=0)
    direction: str = Field("above", pattern=r'^(above|below)$')


class RebalanceScheduleRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="调度名称")
    symbols: str = Field(..., min_length=3, description="逗号分隔的股票代码")
    frequency: str = Field("weekly", pattern=r"^(daily|weekly|monthly)$", description="检查频率")
    drift_threshold: float = Field(0.05, ge=0.01, le=0.20, description="偏离阈值")
    turnover_cap: float = Field(0.30, ge=0.05, le=1.0, description="换手上限")
    capital: float = Field(100000, ge=10000, le=10000000, description="总资金")
    period: str = Field("1y", max_length=5, description="回看周期")


class FactorPipelineRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    period: str = Field(default="1y", max_length=5)
    winsorize_lower: float = Field(default=0.025, ge=0.0, le=0.5)
    winsorize_upper: float = Field(default=0.975, ge=0.5, le=1.0)
    neutralize_method: str = Field(default="zscore", pattern=r"^(zscore|rank)$")
    industry_neutralize: bool = Field(default=False)
    market_cap_neutralize: bool = Field(default=False)
    orthogonalize: bool = Field(default=True)


class MultiSymbolBacktestRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2, max_length=20)
    strategy_name: str = Field(default="DualMAStrategy", max_length=50)
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    position_method: str = Field(default="equal_weight")
    correlation_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_positions: int = Field(default=5, ge=1, le=50)
    max_workers: int = Field(default=4, ge=1, le=16)
    parallel: bool = Field(default=True)


class PortfolioImportRequest(BaseModel):
    data: dict


class TCAAnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    strategy_name: str = Field(default="default", max_length=50)
    side: str = Field(default="buy", pattern=r"^(buy|sell)$")
    decision_price: float = Field(..., gt=0)
    arrival_price: float = Field(..., gt=0)
    execution_price: float = Field(..., gt=0)
    vwap_benchmark: float = Field(default=0, ge=0)
    twap_benchmark: float = Field(default=0, ge=0)
    quantity: int = Field(..., gt=0)
    execution_timestamp: str = Field(default="")


class TCABatchRequest(BaseModel):
    trades: list[TCAAnalyzeRequest] = Field(..., min_length=1, max_length=100)


class TCAExecutionRecommendRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)


class BlackLittermanRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2, max_length=20)
    views: list[dict[str, Any]] = Field(default_factory=list)
    market_weights: dict[str, float] | None = Field(None)
    view_confidences: list[float] | None = Field(None)
    risk_free_rate: float = Field(0.03, ge=0.0, le=0.2)
    tau: float = Field(0.05, ge=0.001, le=1.0)
    risk_aversion: float = Field(2.5, ge=0.1, le=10.0)
    period: str = Field("1y", max_length=5)


class MonteCarloVaRRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=20)
    weights: list[float] | None = Field(None)
    confidence_level: float = Field(0.95, ge=0.9, le=0.99)
    time_horizon: int = Field(1, ge=1, le=252)
    n_simulations: int = Field(10000, ge=1000, le=100000)
    method: str = Field("parametric", pattern=r"^(parametric|historical)$")
    period: str = Field("1y", max_length=5)


class SeasonalityRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    period: str = Field("3y", max_length=5)


class CointegrationTestRequest(BaseModel):
    symbol_y: str = Field(..., min_length=1, max_length=20)
    symbol_x: str = Field(..., min_length=1, max_length=20)
    method: str = Field("engle_granger", pattern=r"^(engle_granger|johansen)$")
    significance: float = Field(0.05, ge=0.01, le=0.20)
    period: str = Field("1y", max_length=5)


class PairMiningRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2, max_length=30)
    method: str = Field("engle_granger", pattern=r"^(engle_granger|johansen)$")
    pvalue_threshold: float = Field(0.05, ge=0.01, le=0.20)
    period: str = Field("1y", max_length=5)


class TWAPSimulationRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    total_qty: int = Field(..., gt=0, le=10000000)
    n_slices: int = Field(10, ge=1, le=100)
    duration_minutes: int = Field(60, ge=1, le=480)
    jitter_pct: float = Field(0.0, ge=0.0, le=0.5)


class FeatureFlagUpdateRequest(BaseModel):
    enabled: bool = Field(..., description="功能开关状态")
    rollout_percentage: float | None = Field(None, ge=0.0, le=100.0, description="灰度发布百分比")


class FeatureFlagRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="功能开关名称")
    description: str = Field(..., description="功能开关描述")
    enabled: bool = Field(True, description="初始状态")
    tags: list[str] = Field([], description="标签列表")


class ReadinessCheckResponse(BaseModel):
    status: str = Field(..., description="ready / not_ready / degraded")
    checks: dict[str, str] = Field(..., description="各子系统状态")
    timestamp: str = Field(..., description="ISO格式时间戳")


class StrategyHealthReport(BaseModel):
    strategy: str
    status: str = Field(..., description="healthy / degraded / error")
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    issues: list[str] = Field([], description="健康问题列表")
    error: str = ""


class StrategyHealthResponse(BaseModel):
    symbol: str
    total_strategies: int
    healthy: int
    degraded: int
    errors: int
    reports: list[StrategyHealthReport]


class WalkForwardResponse(BaseModel):
    n_windows: int = 0
    is_median_sharpe: float = 0.0
    oos_median_sharpe: float = 0.0
    wfa_efficiency: float = 0.0
    oos_profitable_pct: float = 0.0
    is_oos_ratio: str = ""
    curve_fitted: bool = False


class DiagnoseRequest(BaseModel):
    strategy: str = Field(..., min_length=1, max_length=100, description="策略名称")
    symbol: str = Field("000001", max_length=20, description="股票代码")


class AnalyzeBacktestRequest(BaseModel):
    strategy: dict = Field(default_factory=dict, description="策略定义数据")
    result: dict = Field(default_factory=dict, description="回测结果数据")


class WalkForwardRequest(BaseModel):
    strategy: str = Field(..., min_length=1, max_length=100, description="策略名称")
    symbol: str = Field("000001", max_length=20, description="股票代码")
    is_window: int = Field(252, ge=20, description="样本内窗口")
    oos_window: int = Field(63, ge=5, description="样本外窗口")
    base_params: dict | None = Field(None, description="基础参数")
    param_ranges: dict | None = Field(None, description="参数搜索范围")
    metric: str = Field("sharpe_ratio", max_length=50, description="优化指标")
    anchored: bool = Field(False, description="是否锚定回测")


class AutoOptimizeRequest(BaseModel):
    strategy: str = Field(..., min_length=1, max_length=100, description="策略名称")
    symbol: str = Field("000001", max_length=20, description="股票代码")
    is_window: int = Field(252, ge=20, description="样本内窗口")
    oos_window: int = Field(63, ge=5, description="样本外窗口")
    metric: str = Field("sharpe_ratio", max_length=50, description="优化指标")
    param_ranges: dict | None = Field(None, description="参数搜索范围")


class CompareStrategiesRequest(BaseModel):
    strategies: list[str] = Field(..., min_length=1, max_length=20, description="策略列表")
    symbol: str = Field("000001", max_length=20, description="股票代码")
    period: str = Field("1y", max_length=10, description="回测周期")


class SensitivityHeatmapRequest(BaseModel):
    strategy: str = Field(..., min_length=1, max_length=100, description="策略名称")
    symbol: str = Field("000001", max_length=20, description="股票代码")
    param_x: str = Field(..., min_length=1, max_length=50, description="X轴参数名")
    param_x_values: list[float] = Field(..., min_length=2, max_length=20, description="X轴参数值列表")
    param_y: str = Field(..., min_length=1, max_length=50, description="Y轴参数名")
    param_y_values: list[float] = Field(..., min_length=2, max_length=20, description="Y轴参数值列表")
    metric: str = Field("sharpe_ratio", max_length=50, description="热力图指标")
    period: str = Field("1y", max_length=10, description="回测周期")


class SignalReplayRequest(BaseModel):
    strategy: str = Field(..., min_length=1, max_length=100, description="策略名称")
    symbol: str = Field("000001", max_length=20, description="股票代码")
    start_bar: int = Field(0, ge=0, description="起始bar索引")
    end_bar: int = Field(50, ge=1, le=500, description="结束bar索引")
    params: dict | None = Field(None, description="策略参数覆盖")


class JournalEntryRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    name: str = Field("", max_length=20)
    trade_type: str = Field("buy", pattern=r'^(buy|sell)$')
    price: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0, le=1000000)
    notes: str = Field("", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    emotion: str = Field("", max_length=20)
    rating: int = Field(0, ge=0, le=5)


class StressTestRequest(BaseModel):
    positions: list[dict] = Field(default_factory=list, max_length=100)
    run_monte_carlo: bool = Field(False)


class JournalUpdateRequest(BaseModel):
    symbol: str | None = Field(None, min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    name: str | None = Field(None, max_length=20)
    trade_type: str | None = Field(None, pattern=r'^(buy|sell)$')
    price: float | None = Field(None, gt=0)
    quantity: int | None = Field(None, gt=0, le=1000000)
    notes: str | None = Field(None, max_length=2000)
    tags: list[str] | None = Field(None, max_length=10)
    emotion: str | None = Field(None, max_length=20)
    rating: int | None = Field(None, ge=0, le=5)


class RiskParityRequest(BaseModel):
    capital: float = Field(1000000, gt=0, le=100000000)
    positions: list[dict] = Field(default_factory=list, max_length=100)


class FactorAttributionRequest(BaseModel):
    symbols: str = Field(..., min_length=1, max_length=300, description="逗号分隔的股票代码")
    period: str = Field("1y", max_length=5, description="时间范围")
    risk_free_rate: float = Field(0.03, ge=0.0, le=0.5, description="无风险利率")
    factors: list[str] = Field(default_factory=lambda: ["MKT", "SMB", "HML"], description="因子列表")


class RegimeDetectRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, description="股票代码")
    period: str = Field("1y", max_length=5, description="历史数据范围")
    n_states: int = Field(3, ge=2, le=6, description="HMM状态数")


class GarchVolatilityRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, description="股票代码")
    period: str = Field("1y", max_length=5, description="历史数据范围")
    iterations: int = Field(5, ge=1, le=20, description="GARCH拟合迭代次数")


class RiskParityOptimizeRequest(BaseModel):
    symbols: str = Field(..., min_length=3, max_length=300, description="逗号分隔的股票代码列表")
    period: str = Field("1y", max_length=5, description="历史数据范围")
    drift_threshold: float = Field(0.05, ge=0.01, le=0.20, description="权重漂移阈值")
    turnover_cap: float = Field(0.30, ge=0.05, le=1.0, description="换手率上限")


class PortfolioAnalyticsRequest(BaseModel):
    symbols: str = Field(..., min_length=3, max_length=300, description="逗号分隔的股票代码列表")
    period: str = Field("1y", max_length=5, description="历史数据范围")
    n_simulations: int = Field(5000, ge=1000, le=50000, description="蒙特卡洛模拟次数")
    time_horizon: int = Field(1, ge=1, le=22, description="风险预测天数")
    n_regime_states: int = Field(3, ge=2, le=6, description="HMM状态数")
    include_factor_attribution: bool = Field(True, description="是否包含因子归因")
    include_regime: bool = Field(True, description="是否包含市场状态检测")
    include_var: bool = Field(True, description="是否包含蒙特卡洛VaR")
    include_risk_parity: bool = Field(True, description="是否包含风险平价优化")
