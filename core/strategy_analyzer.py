from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from core.strategy_schema import (
    AssetClass,
    MarketType,
    PositionSizing,
    StopLossType,
    StrategyDefinition,
    TakeProfitType,
)

logger = logging.getLogger(__name__)


class MarketRegime(StrEnum):
    BULL_TREND = "bull_trend"
    BEAR_TREND = "bear_trend"
    HIGH_VOL_CHOP = "high_vol_chop"
    LOW_VOL_CHOP = "low_vol_chop"


@dataclass
class RegimePerformance:
    regime: MarketRegime
    expected_sharpe: float
    expected_return_pct: float
    expected_max_dd_pct: float
    confidence: str


@dataclass
class EdgeAnalysis:
    alpha_source: str
    optimal_regime: str
    lookahead_bias_risks: list[str]
    survivorship_bias_risks: list[str]
    overfitting_risk: str


@dataclass
class IndicatorDependency:
    name: str
    lookback: int
    min_bars_before_signal: int


@dataclass
class Weakness:
    title: str
    description: str
    severity: str
    mitigation: str


@dataclass
class Improvement:
    title: str
    description: str
    expected_impact: str
    implementation_effort: str


@dataclass
class StrategyAnalysis:
    edge: EdgeAnalysis
    indicator_dependencies: list[IndicatorDependency]
    regime_sensitivity: list[RegimePerformance]
    weaknesses: list[Weakness]
    improvements: list[Improvement]


_ALPHA_SOURCES: dict[MarketType, str] = {
    MarketType.TREND: "价格动量 — 依赖趋势持续性，在方向性市场中获利",
    MarketType.MEAN_REVERSION: "均值回归 — 利用价格偏离统计均值的回归特性",
    MarketType.MOMENTUM: "因子动量 — 基于近期价格/成交量的惯性效应",
    MarketType.ARBITRAGE: "统计套利 — 利用资产间协整关系的暂时偏离",
    MarketType.MARKET_MAKING: "买卖价差 — 通过提供流动性赚取bid-ask spread",
    MarketType.ML_DRIVEN: "机器学习信号 — 基于历史模式识别的非线性预测",
}

_REGIME_PERF_TEMPLATES: dict[MarketType, dict[MarketRegime, tuple[float, float, float]]] = {
    MarketType.TREND: {
        MarketRegime.BULL_TREND: (1.2, 25.0, 10.0),
        MarketRegime.BEAR_TREND: (0.6, -5.0, 20.0),
        MarketRegime.HIGH_VOL_CHOP: (0.2, 2.0, 25.0),
        MarketRegime.LOW_VOL_CHOP: (0.4, 8.0, 12.0),
    },
    MarketType.MEAN_REVERSION: {
        MarketRegime.BULL_TREND: (0.3, 5.0, 15.0),
        MarketRegime.BEAR_TREND: (0.2, -2.0, 25.0),
        MarketRegime.HIGH_VOL_CHOP: (0.8, 15.0, 18.0),
        MarketRegime.LOW_VOL_CHOP: (1.0, 12.0, 8.0),
    },
    MarketType.MOMENTUM: {
        MarketRegime.BULL_TREND: (1.0, 20.0, 12.0),
        MarketRegime.BEAR_TREND: (0.5, -8.0, 22.0),
        MarketRegime.HIGH_VOL_CHOP: (0.1, 0.0, 30.0),
        MarketRegime.LOW_VOL_CHOP: (0.6, 10.0, 10.0),
    },
    MarketType.ARBITRAGE: {
        MarketRegime.BULL_TREND: (0.7, 8.0, 5.0),
        MarketRegime.BEAR_TREND: (0.7, 8.0, 5.0),
        MarketRegime.HIGH_VOL_CHOP: (0.9, 12.0, 8.0),
        MarketRegime.LOW_VOL_CHOP: (0.5, 5.0, 3.0),
    },
    MarketType.MARKET_MAKING: {
        MarketRegime.BULL_TREND: (0.5, 6.0, 8.0),
        MarketRegime.BEAR_TREND: (0.3, 3.0, 15.0),
        MarketRegime.HIGH_VOL_CHOP: (0.2, 1.0, 25.0),
        MarketRegime.LOW_VOL_CHOP: (1.2, 10.0, 4.0),
    },
    MarketType.ML_DRIVEN: {
        MarketRegime.BULL_TREND: (0.6, 12.0, 15.0),
        MarketRegime.BEAR_TREND: (0.4, -3.0, 20.0),
        MarketRegime.HIGH_VOL_CHOP: (0.3, 5.0, 22.0),
        MarketRegime.LOW_VOL_CHOP: (0.5, 8.0, 12.0),
    },
}


def analyze_strategy(definition: StrategyDefinition, backtest_trades: int = 0, backtest_period_years: float = 0.0) -> StrategyAnalysis:
    n_params = len(definition.parameters)
    edge = _analyze_edge(definition, n_params, backtest_trades, backtest_period_years)
    deps = _analyze_indicator_dependencies(definition)
    regimes = _analyze_regime_sensitivity(definition)
    weaknesses = _analyze_weaknesses(definition)
    improvements = _suggest_improvements(definition, weaknesses)
    return StrategyAnalysis(
        edge=edge,
        indicator_dependencies=deps,
        regime_sensitivity=regimes,
        weaknesses=weaknesses,
        improvements=improvements,
    )


def _analyze_edge(definition: StrategyDefinition, n_params: int, n_trades: int, period_years: float) -> EdgeAnalysis:
    meta = definition.strategy_meta
    alpha_source = _ALPHA_SOURCES.get(meta.market_type, "未知alpha来源")
    optimal_regime = {
        MarketType.TREND: "趋势行情（低波动率+方向性）",
        MarketType.MEAN_REVERSION: "震荡行情（区间波动+高波动率）",
        MarketType.MOMENTUM: "动量行情（强趋势+高换手）",
        MarketType.ARBITRAGE: "高相关性+暂时偏离",
        MarketType.MARKET_MAKING: "高流动性+窄价差",
        MarketType.ML_DRIVEN: "数据充足+模式稳定",
    }.get(meta.market_type, "未知")

    lookahead = []
    for cond in definition.signal_logic.filter_conditions + [
        definition.signal_logic.entry_long,
        definition.signal_logic.entry_short,
        definition.signal_logic.exit_long,
        definition.signal_logic.exit_short,
    ]:
        if not cond:
            continue
        lower = cond.lower()
        if any(kw in lower for kw in ("future", "lookahead", "peek", "明天", "未来")):
            lookahead.append(f"信号条件 '{cond}' 可能包含前瞻偏差")

    survivorship = []
    if meta.asset_class in (AssetClass.SPOT, AssetClass.CRYPTO):
        survivorship.append("使用当前存续股票池可能忽略已退市标的，导致幸存者偏差")

    if n_trades > 0 and n_params > 0:
        ratio = n_params * 100 / max(n_trades, 1)
        if ratio > 50:
            overfitting = "high"
        elif ratio > 20:
            overfitting = "medium"
        else:
            overfitting = "low"
    else:
        overfitting = "medium" if n_params > 5 else "low"

    return EdgeAnalysis(
        alpha_source=alpha_source,
        optimal_regime=optimal_regime,
        lookahead_bias_risks=lookahead,
        survivorship_bias_risks=survivorship,
        overfitting_risk=overfitting,
    )


def _analyze_indicator_dependencies(definition: StrategyDefinition) -> list[IndicatorDependency]:
    deps = []
    for ind in definition.indicators:
        lookback = 0
        for v in ind.params.values():
            if isinstance(v, (int, float)) and v > lookback:
                lookback = int(v)
        if lookback == 0:
            lookback = 14
        min_bars = lookback * 3
        deps.append(IndicatorDependency(
            name=ind.name,
            lookback=lookback,
            min_bars_before_signal=min_bars,
        ))
    if not deps:
        deps.append(IndicatorDependency(name="default", lookback=14, min_bars_before_signal=42))
    return deps


def _analyze_regime_sensitivity(definition: StrategyDefinition) -> list[RegimePerformance]:
    templates = _REGIME_PERF_TEMPLATES.get(definition.strategy_meta.market_type, _REGIME_PERF_TEMPLATES[MarketType.TREND])
    results = []
    for regime, (sharpe, ret, dd) in templates.items():
        has_stop = definition.risk_management.stop_loss.type != StopLossType.NONE
        has_tp = definition.risk_management.take_profit.type != TakeProfitType.NONE
        if has_stop:
            dd *= 0.7
        if has_tp:
            ret *= 0.85
        if definition.risk_management.position_sizing == PositionSizing.ATR_BASED:
            sharpe *= 1.15
        confidence = "high" if abs(sharpe) > 0.8 else ("medium" if abs(sharpe) > 0.4 else "low")
        results.append(RegimePerformance(
            regime=regime,
            expected_sharpe=round(sharpe, 2),
            expected_return_pct=round(ret, 1),
            expected_max_dd_pct=round(dd, 1),
            confidence=confidence,
        ))
    return results


def _analyze_weaknesses(definition: StrategyDefinition) -> list[Weakness]:
    weaknesses = []
    meta = definition.strategy_meta
    rm = definition.risk_management

    if meta.market_type == MarketType.TREND:
        weaknesses.append(Weakness(
            title="震荡市锯齿风险",
            description="趋势跟踪策略在横盘震荡市中频繁产生虚假信号，导致连续小额亏损",
            severity="high",
            mitigation="添加ADX或波动率过滤器，仅在趋势强度确认时入场",
        ))

    if rm.stop_loss.type == StopLossType.NONE:
        weaknesses.append(Weakness(
            title="无止损保护",
            description="未设置止损，单笔交易可能造成重大损失，黑天鹅事件下可能爆仓",
            severity="critical",
            mitigation="至少添加固定百分比止损（如5%），推荐ATR倍数止损",
        ))

    if rm.leverage > 3.0:
        weaknesses.append(Weakness(
            title="高杠杆风险",
            description=f"杠杆倍数{rm.leverage}x，小幅逆向波动即可触发强制平仓",
            severity="high",
            mitigation="降低杠杆至2x以下，或添加更严格的止损",
        ))

    if meta.timeframe.value in ("1m", "5m", "15m"):
        weaknesses.append(Weakness(
            title="日内滑点与延迟风险",
            description="高频策略对执行延迟敏感，回测假设的即时成交在实际中难以实现",
            severity="medium",
            mitigation="使用限价单替代市价单，添加延迟模拟",
        ))

    if meta.market_type == MarketType.MEAN_REVERSION:
        weaknesses.append(Weakness(
            title="趋势崩溃风险",
            description="均值回归策略在趋势形成时持续逆势加仓，可能导致巨额亏损",
            severity="high",
            mitigation="添加趋势过滤器，在强趋势中暂停交易或减小仓位",
        ))

    if not rm.daily_loss_limit_pct:
        weaknesses.append(Weakness(
            title="无日内亏损限制",
            description="缺乏日内最大亏损限制，极端行情下可能持续亏损",
            severity="medium",
            mitigation="设置日内最大亏损2-3%，触发后暂停交易",
        ))

    if len(definition.parameters) > 8:
        weaknesses.append(Weakness(
            title="参数过多风险",
            description=f"策略有{len(definition.parameters)}个参数，过拟合风险较高",
            severity="medium",
            mitigation="减少参数数量，使用Walk-Forward验证",
        ))

    if not weaknesses:
        weaknesses.append(Weakness(
            title="模型风险",
            description="所有量化策略都存在模型假设失效的风险",
            severity="low",
            mitigation="持续监控策略表现，设置策略降级阈值",
        ))

    return weaknesses


def _suggest_improvements(definition: StrategyDefinition, weaknesses: list[Weakness]) -> list[Improvement]:
    improvements = []
    rm = definition.risk_management
    meta = definition.strategy_meta

    if rm.stop_loss.type == StopLossType.NONE:
        improvements.append(Improvement(
            title="添加ATR止损",
            description="基于ATR(14)设置2倍ATR止损，可适应不同波动率环境，预计减少最大回撤30-40%",
            expected_impact="减少最大回撤30-40%，略降低总收益5%",
            implementation_effort="low",
        ))

    if rm.position_sizing == PositionSizing.FIXED:
        improvements.append(Improvement(
            title="波动率调整仓位",
            description="将固定仓位改为ATR归一化仓位（1%组合风险/ATR单位），平滑不同波动率环境的风险敞口",
            expected_impact="平滑权益曲线，提高Sharpe约0.2-0.4",
            implementation_effort="medium",
        ))

    if meta.market_type == MarketType.TREND:
        improvements.append(Improvement(
            title="添加ADX趋势过滤器",
            description="添加ADX(14)>25过滤条件，仅在趋势确认时交易，减少震荡市虚假信号约40%",
            expected_impact="减少交易次数约40%，提高Sharpe约0.3-0.5",
            implementation_effort="low",
        ))

    if not rm.daily_loss_limit_pct:
        improvements.append(Improvement(
            title="设置日内亏损限制",
            description="添加2%日内最大亏损限制，触发后暂停新开仓，防止极端行情下的持续亏损",
            expected_impact="限制尾部风险，减少极端亏损日",
            implementation_effort="low",
        ))

    if meta.market_type == MarketType.MEAN_REVERSION:
        improvements.append(Improvement(
            title="添加趋势状态检测",
            description="使用Hurst指数或ADXR判断市场状态，在趋势市中暂停或减小均值回归仓位",
            expected_impact="减少趋势崩溃损失约50%",
            implementation_effort="medium",
        ))

    if len(definition.parameters) > 5:
        improvements.append(Improvement(
            title="Walk-Forward验证",
            description="使用3:1 IS:OOS滚动窗口验证参数稳定性，WFA效率>0.5为可接受",
            expected_impact="验证策略非过拟合，提高实盘信心",
            implementation_effort="high",
        ))

    if not improvements:
        improvements.append(Improvement(
            title="持续监控机制",
            description="建立策略表现监控，当滚动Sharpe低于阈值时自动降级",
            expected_impact="防止策略失效后继续运行",
            implementation_effort="medium",
        ))

    return improvements


def analyze_backtest_result(
    definition: StrategyDefinition,
    result_dict: dict,
) -> dict:
    analysis = analyze_strategy(
        definition,
        backtest_trades=result_dict.get("total_trades", 0),
        backtest_period_years=0,
    )
    red_flags = []
    n_trades = result_dict.get("total_trades", 0)
    if n_trades < 15:
        red_flags.append(f"交易次数过少({n_trades}次)，统计结论不可靠")
    elif n_trades < 30:
        red_flags.append(f"交易次数偏少({n_trades}次)，结论需谨慎")
    sharpe = result_dict.get("sharpe_ratio", 0)
    if sharpe > 3.0:
        red_flags.append(f"Sharpe={sharpe:.1f}异常高，可能过拟合")
    win_rate = result_dict.get("win_rate", 0)
    if win_rate > 0 and win_rate < 30:
        red_flags.append(f"胜率仅{win_rate:.0f}%，需要更高的盈亏比才能盈利")
    max_dd = result_dict.get("max_drawdown", 0)
    if max_dd > 0.4:
        red_flags.append(f"最大回撤{max_dd*100:.1f}%过高，超出机构可接受范围")
    return {
        "edge_analysis": {
            "alpha_source": analysis.edge.alpha_source,
            "optimal_regime": analysis.edge.optimal_regime,
            "lookahead_bias_risks": analysis.edge.lookahead_bias_risks,
            "survivorship_bias_risks": analysis.edge.survivorship_bias_risks,
            "overfitting_risk": analysis.edge.overfitting_risk,
        },
        "indicator_dependencies": [
            {"name": d.name, "lookback": d.lookback, "min_bars_before_signal": d.min_bars_before_signal}
            for d in analysis.indicator_dependencies
        ],
        "regime_sensitivity": [
            {
                "regime": r.regime.value,
                "expected_sharpe": r.expected_sharpe,
                "expected_return_pct": r.expected_return_pct,
                "expected_max_dd_pct": r.expected_max_dd_pct,
                "confidence": r.confidence,
            }
            for r in analysis.regime_sensitivity
        ],
        "weaknesses": [
            {"title": w.title, "description": w.description, "severity": w.severity, "mitigation": w.mitigation}
            for w in analysis.weaknesses
        ],
        "improvements": [
            {"title": i.title, "description": i.description, "expected_impact": i.expected_impact, "effort": i.implementation_effort}
            for i in analysis.improvements
        ],
        "red_flags": red_flags,
        "disclaimer": "Past backtest results do not guarantee future performance. All metrics are subject to estimation error.",
    }
