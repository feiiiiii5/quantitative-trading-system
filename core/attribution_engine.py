__all__ = [
    "BrinsonResult",
    "FactorAttributionResult",
    "RegimeAttributionResult",
    "TradeAttributionResult",
    "AttributionReport",
    "AttributionContext",
    "AttributionEngine",
    "brinson_attribution",
    "factor_attribution",
    "regime_attribution",
    "trade_attribution",
    "generate_monthly_report",
]

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BrinsonResult:
    total_excess: float = 0.0
    allocation_effect: float = 0.0
    selection_effect: float = 0.0
    interaction_effect: float = 0.0
    category_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class FactorAttributionResult:
    factor_contributions: dict[str, float] = field(default_factory=dict)
    specific_return: float = 0.0
    r_squared: float = 0.0
    total_return: float = 0.0


@dataclass
class RegimeAttributionResult:
    regime_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    dominant_regime: str = ""


@dataclass
class TradeAttributionResult:
    total_pnl: float = 0.0
    holding_pnl: float = 0.0
    timing_pnl: float = 0.0
    friction_cost: float = 0.0
    trade_breakdown: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AttributionReport:
    period: str = ""
    brinson: BrinsonResult | None = None
    factor: FactorAttributionResult | None = None
    regime: RegimeAttributionResult | None = None
    trade: TradeAttributionResult | None = None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class AttributionContext:
    portfolio_weights: dict[str, float] = field(default_factory=dict)
    benchmark_weights: dict[str, float] = field(default_factory=dict)
    asset_returns: dict[str, float] = field(default_factory=dict)
    category_returns: dict[str, float] = field(default_factory=dict)
    portfolio_returns: pd.Series | None = None
    factor_exposure_matrix: pd.DataFrame | None = None
    factor_returns: pd.Series | None = None
    regime_labels: pd.Series | None = None
    trades: list[dict[str, Any]] = field(default_factory=list)
    date_range: tuple[str, str] = ("", "")


def brinson_attribution(
    portfolio_weights: dict[str, float],
    benchmark_weights: dict[str, float],
    asset_returns: dict[str, float],
    category_returns: dict[str, float],
) -> BrinsonResult:
    if not portfolio_weights or not benchmark_weights or not category_returns:
        logger.debug("Brinson归因输入为空")
        return BrinsonResult()

    all_categories = set(portfolio_weights) | set(benchmark_weights)
    if not all_categories:
        return BrinsonResult()

    total_allocation = 0.0
    total_selection = 0.0
    total_interaction = 0.0
    category_breakdown: dict[str, dict[str, float]] = {}

    for cat in all_categories:
        wp = portfolio_weights.get(cat, 0.0)
        wb = benchmark_weights.get(cat, 0.0)
        rb = category_returns.get(cat, 0.0)

        cat_assets = {k: v for k, v in asset_returns.items() if k.startswith(cat + ":")}
        if cat_assets:
            rp = (
                sum(wp * asset_returns.get(a, 0.0) for a in cat_assets) / wp
                if abs(wp) > 1e-12
                else rb
            )
        else:
            rp = category_returns.get(cat, 0.0)

        alloc = (wp - wb) * rb
        select = wb * (rp - rb)
        interact = (wp - wb) * (rp - rb)

        total_allocation += alloc
        total_selection += select
        total_interaction += interact

        category_breakdown[cat] = {
            "allocation": round(alloc, 6),
            "selection": round(select, 6),
            "interaction": round(interact, 6),
            "portfolio_weight": round(wp, 6),
            "benchmark_weight": round(wb, 6),
            "portfolio_return": round(rp, 6),
            "benchmark_return": round(rb, 6),
        }

    total_excess = total_allocation + total_selection + total_interaction

    return BrinsonResult(
        total_excess=round(total_excess, 6),
        allocation_effect=round(total_allocation, 6),
        selection_effect=round(total_selection, 6),
        interaction_effect=round(total_interaction, 6),
        category_breakdown=category_breakdown,
    )


def factor_attribution(
    portfolio_returns: pd.Series,
    factor_exposure_matrix: pd.DataFrame,
    factor_returns: pd.Series,
) -> FactorAttributionResult:
    if portfolio_returns is None or portfolio_returns.empty:
        logger.debug("因子归因: 组合收益为空")
        return FactorAttributionResult()

    if factor_exposure_matrix is None or factor_exposure_matrix.empty:
        logger.debug("因子归因: 因子暴露矩阵为空")
        return FactorAttributionResult()

    if factor_returns is None or factor_returns.empty:
        logger.debug("因子归因: 因子收益为空")
        return FactorAttributionResult()

    common_idx = portfolio_returns.index.intersection(
        factor_exposure_matrix.index
    ).intersection(factor_returns.index)

    if len(common_idx) < 5:
        logger.debug("因子归因: 公共时间点不足5个, 得到%d", len(common_idx))
        return FactorAttributionResult()

    pr = portfolio_returns.loc[common_idx].values.astype(float)
    exposures = factor_exposure_matrix.loc[common_idx].values.astype(float)
    fr = factor_returns.loc[common_idx].values.astype(float)

    total_return = float(np.sum(pr))

    if exposures.shape[1] != len(fr):
        logger.debug(
            "因子归因: 暴露列数(%d)与因子收益长度(%d)不匹配",
            exposures.shape[1],
            len(fr),
        )
        return FactorAttributionResult(total_return=round(total_return, 6))

    mean_exposure = np.mean(exposures, axis=0)
    factor_contributions: dict[str, float] = {}
    explained = 0.0

    factor_names = list(factor_exposure_matrix.columns)
    for i, name in enumerate(factor_names):
        contrib = float(mean_exposure[i] * fr[i])
        factor_contributions[name] = round(contrib, 6)
        explained += contrib

    specific_return = total_return - explained

    try:
        mean_pr = np.mean(pr)
        ss_total = float(np.sum((pr - mean_pr) ** 2))
        if ss_total > 1e-12:
            predicted = exposures @ fr
            ss_residual = float(np.sum((pr - predicted) ** 2))
            r_squared = max(0.0, 1.0 - ss_residual / ss_total)
        else:
            r_squared = 0.0
    except Exception as e:
        logger.debug("因子归因R²计算失败: %s", e)
        r_squared = 0.0

    return FactorAttributionResult(
        factor_contributions=factor_contributions,
        specific_return=round(specific_return, 6),
        r_squared=round(r_squared, 4),
        total_return=round(total_return, 6),
    )


def regime_attribution(
    returns: pd.Series,
    regime_labels: pd.Series,
) -> RegimeAttributionResult:
    if returns is None or returns.empty:
        logger.debug("市场状态归因: 收益序列为空")
        return RegimeAttributionResult()

    if regime_labels is None or regime_labels.empty:
        logger.debug("市场状态归因: 状态标签为空")
        return RegimeAttributionResult()

    common_idx = returns.index.intersection(regime_labels.index)
    if len(common_idx) < 5:
        logger.debug("市场状态归因: 公共时间点不足5个")
        return RegimeAttributionResult()

    aligned_returns = returns.loc[common_idx]
    aligned_labels = regime_labels.loc[common_idx]

    regime_breakdown: dict[str, dict[str, float]] = {}
    total_return = float(np.sum(aligned_returns))

    for regime in aligned_labels.unique():
        regime_mask = aligned_labels == regime
        regime_returns = aligned_returns[regime_mask]
        n_periods = len(regime_returns)
        regime_total = float(np.sum(regime_returns))
        contribution = regime_total / total_return if abs(total_return) > 1e-12 else 0.0

        regime_breakdown[str(regime)] = {
            "total_return": round(regime_total, 6),
            "mean_return": round(float(np.mean(regime_returns)), 6),
            "volatility": round(float(np.std(regime_returns, ddof=1)), 6) if n_periods > 1 else 0.0,
            "n_periods": n_periods,
            "contribution": round(contribution, 4),
            "weight": round(n_periods / len(aligned_returns), 4),
        }

    dominant_regime = ""
    if regime_breakdown:
        dominant_regime = max(
            regime_breakdown,
            key=lambda r: abs(regime_breakdown[r]["contribution"]),
        )

    return RegimeAttributionResult(
        regime_breakdown=regime_breakdown,
        dominant_regime=dominant_regime,
    )


def trade_attribution(
    trades: list[dict[str, Any]],
) -> TradeAttributionResult:
    if not trades:
        logger.debug("交易归因: 交易列表为空")
        return TradeAttributionResult()

    total_pnl = 0.0
    total_holding = 0.0
    total_timing = 0.0
    total_friction = 0.0
    trade_breakdown: list[dict[str, Any]] = []

    for trade in trades:
        entry_price = trade.get("entry_price", 0.0)
        exit_price = trade.get("exit_price", 0.0)
        quantity = trade.get("quantity", 0)
        decision_price = trade.get("decision_price", entry_price)
        arrival_price = trade.get("arrival_price", entry_price)
        commission = trade.get("commission", 0.0)
        slippage = trade.get("slippage", 0.0)
        symbol = trade.get("symbol", "unknown")
        side = trade.get("side", "buy")

        if side == "buy":
            holding = (exit_price - entry_price) * quantity
            timing = (arrival_price - decision_price) * quantity
        else:
            holding = (entry_price - exit_price) * quantity
            timing = (decision_price - arrival_price) * quantity

        friction = commission + slippage
        trade_pnl = holding + timing - friction

        total_pnl += trade_pnl
        total_holding += holding
        total_timing += timing
        total_friction += friction

        trade_breakdown.append({
            "symbol": symbol,
            "side": side,
            "pnl": round(trade_pnl, 6),
            "holding_pnl": round(holding, 6),
            "timing_pnl": round(timing, 6),
            "friction_cost": round(friction, 6),
        })

    return TradeAttributionResult(
        total_pnl=round(total_pnl, 6),
        holding_pnl=round(total_holding, 6),
        timing_pnl=round(total_timing, 6),
        friction_cost=round(total_friction, 6),
        trade_breakdown=trade_breakdown,
    )


def generate_monthly_report(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    factor_exposures: pd.DataFrame | None,
    factor_returns: pd.Series | None,
    trades: list[dict[str, Any]],
    date_range: tuple[str, str],
) -> AttributionReport:
    period = f"{date_range[0]}~{date_range[1]}" if date_range[0] else ""

    brinson_result: BrinsonResult | None = None
    if portfolio_returns is not None and benchmark_returns is not None:
        common_idx = portfolio_returns.index.intersection(benchmark_returns.index)
        if len(common_idx) > 0:
            pr = portfolio_returns.loc[common_idx]
            br = benchmark_returns.loc[common_idx]
            excess = pr - br

            if len(excess) > 0:
                monthly_groups = excess.groupby(excess.index.to_period("M"))
                cat_returns: dict[str, float] = {}
                for period_key, group in monthly_groups:
                    cat_returns[str(period_key)] = float(np.sum(group))

                port_total = float(np.sum(pr))
                bench_total = float(np.sum(br))
                total_weight = abs(port_total) + abs(bench_total)
                if total_weight > 1e-12:
                    pw = {"portfolio": abs(port_total) / total_weight}
                    bw = {"portfolio": abs(bench_total) / total_weight}
                else:
                    pw = {"portfolio": 1.0}
                    bw = {"portfolio": 1.0}

                asset_rets = {"portfolio:main": float(port_total)}
                brinson_result = brinson_attribution(pw, bw, asset_rets, cat_returns)

    factor_result: FactorAttributionResult | None = None
    if (
        portfolio_returns is not None
        and factor_exposures is not None
        and factor_returns is not None
    ):
        factor_result = factor_attribution(
            portfolio_returns, factor_exposures, factor_returns
        )

    regime_result: RegimeAttributionResult | None = None
    if portfolio_returns is not None and benchmark_returns is not None:
        common_idx = portfolio_returns.index.intersection(benchmark_returns.index)
        if len(common_idx) > 10:
            pr = portfolio_returns.loc[common_idx]
            br = benchmark_returns.loc[common_idx]
            excess = pr - br

            regime_labels = pd.Series(index=excess.index, dtype=str)
            rolling_vol = excess.rolling(window=20, min_periods=5).std()
            vol_median = rolling_vol.median()

            if pd.notna(vol_median) and vol_median > 1e-12:
                regime_labels[rolling_vol > vol_median * 1.5] = "high_vol"
                regime_labels[rolling_vol < vol_median * 0.5] = "low_vol"
                regime_labels = regime_labels.fillna("normal")
            else:
                regime_labels[:] = "normal"

            regime_result = regime_attribution(excess, regime_labels)

    trade_result: TradeAttributionResult | None = None
    if trades:
        trade_result = trade_attribution(trades)

    summary: dict[str, Any] = {}
    if portfolio_returns is not None and len(portfolio_returns) > 0:
        cum_ret = float(np.prod(1 + portfolio_returns) - 1)
        ann_vol = float(portfolio_returns.std() * np.sqrt(252))
        sharpe = (
            float(portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(252))
            if portfolio_returns.std() > 1e-12
            else 0.0
        )
        summary["portfolio_cumulative_return"] = round(cum_ret, 6)
        summary["annualized_volatility"] = round(ann_vol, 6)
        summary["sharpe_ratio"] = round(sharpe, 4)

    if benchmark_returns is not None and len(benchmark_returns) > 0:
        bench_cum = float(np.prod(1 + benchmark_returns) - 1)
        summary["benchmark_cumulative_return"] = round(bench_cum, 6)

    if brinson_result is not None:
        summary["excess_return"] = brinson_result.total_excess
        summary["allocation_effect"] = brinson_result.allocation_effect
        summary["selection_effect"] = brinson_result.selection_effect

    if factor_result is not None:
        summary["factor_r_squared"] = factor_result.r_squared
        summary["specific_return"] = factor_result.specific_return

    if trade_result is not None:
        summary["total_trade_pnl"] = trade_result.total_pnl
        summary["total_friction_cost"] = trade_result.friction_cost

    return AttributionReport(
        period=period,
        brinson=brinson_result,
        factor=factor_result,
        regime=regime_result,
        trade=trade_result,
        summary=summary,
    )


class AttributionEngine:
    """综合归因引擎

    整合Brinson归因、因子归因、市场状态归因、交易归因，
    提供统一的归因分析和跨期比较能力。
    """

    def __init__(
        self,
        lookback: int = 252,
        regime_vol_window: int = 20,
    ) -> None:
        self._lookback = lookback
        self._regime_vol_window = regime_vol_window

    def run_full_attribution(
        self,
        context: AttributionContext,
    ) -> AttributionReport:
        brinson_result: BrinsonResult | None = None
        if context.portfolio_weights and context.benchmark_weights:
            brinson_result = brinson_attribution(
                context.portfolio_weights,
                context.benchmark_weights,
                context.asset_returns,
                context.category_returns,
            )

        factor_result: FactorAttributionResult | None = None
        if (
            context.portfolio_returns is not None
            and context.factor_exposure_matrix is not None
            and context.factor_returns is not None
        ):
            factor_result = factor_attribution(
                context.portfolio_returns,
                context.factor_exposure_matrix,
                context.factor_returns,
            )

        regime_result: RegimeAttributionResult | None = None
        if (
            context.portfolio_returns is not None
            and context.regime_labels is not None
        ):
            regime_result = regime_attribution(
                context.portfolio_returns,
                context.regime_labels,
            )
        elif (
            context.portfolio_returns is not None
            and context.portfolio_returns.dropna().shape[0] > self._regime_vol_window
        ):
            regime_labels = self._infer_regime_labels(context.portfolio_returns)
            regime_result = regime_attribution(
                context.portfolio_returns,
                regime_labels,
            )

        trade_result: TradeAttributionResult | None = None
        if context.trades:
            trade_result = trade_attribution(context.trades)

        summary = self._build_summary(
            brinson_result, factor_result, regime_result, trade_result, context
        )

        period = (
            f"{context.date_range[0]}~{context.date_range[1]}"
            if context.date_range[0]
            else ""
        )

        return AttributionReport(
            period=period,
            brinson=brinson_result,
            factor=factor_result,
            regime=regime_result,
            trade=trade_result,
            summary=summary,
        )

    def compare_periods(
        self,
        report_a: AttributionReport,
        report_b: AttributionReport,
    ) -> dict[str, Any]:
        comparison: dict[str, Any] = {
            "period_a": report_a.period,
            "period_b": report_b.period,
            "summary_delta": {},
            "brinson_delta": {},
            "factor_delta": {},
            "trade_delta": {},
        }

        all_keys = set(report_a.summary.keys()) | set(report_b.summary.keys())
        for key in all_keys:
            va = report_a.summary.get(key, 0.0)
            vb = report_b.summary.get(key, 0.0)
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                comparison["summary_delta"][key] = round(vb - va, 6)

        if report_a.brinson is not None and report_b.brinson is not None:
            for attr in ("total_excess", "allocation_effect", "selection_effect", "interaction_effect"):
                va = getattr(report_a.brinson, attr, 0.0)
                vb = getattr(report_b.brinson, attr, 0.0)
                comparison["brinson_delta"][attr] = round(vb - va, 6)

        if report_a.factor is not None and report_b.factor is not None:
            all_factors = set(report_a.factor.factor_contributions.keys()) | set(
                report_b.factor.factor_contributions.keys()
            )
            for factor_name in all_factors:
                va = report_a.factor.factor_contributions.get(factor_name, 0.0)
                vb = report_b.factor.factor_contributions.get(factor_name, 0.0)
                comparison["factor_delta"][factor_name] = round(vb - va, 6)

            comparison["factor_delta"]["specific_return"] = round(
                report_b.factor.specific_return - report_a.factor.specific_return, 6
            )
            comparison["factor_delta"]["r_squared"] = round(
                report_b.factor.r_squared - report_a.factor.r_squared, 4
            )

        if report_a.trade is not None and report_b.trade is not None:
            for attr in ("total_pnl", "holding_pnl", "timing_pnl", "friction_cost"):
                va = getattr(report_a.trade, attr, 0.0)
                vb = getattr(report_b.trade, attr, 0.0)
                comparison["trade_delta"][attr] = round(vb - va, 6)

        return comparison

    def _infer_regime_labels(self, returns: pd.Series) -> pd.Series:
        clean = returns.dropna()
        if len(clean) < self._regime_vol_window:
            return pd.Series("normal", index=returns.index)

        rolling_vol = clean.rolling(
            window=self._regime_vol_window, min_periods=5
        ).std()
        vol_median = rolling_vol.median()

        labels = pd.Series("normal", index=returns.index, dtype=str)

        if pd.notna(vol_median) and vol_median > 1e-12:
            high_mask = rolling_vol > vol_median * 1.5
            low_mask = rolling_vol < vol_median * 0.5
            labels.loc[high_mask[high_mask].index] = "high_vol"
            labels.loc[low_mask[low_mask].index] = "low_vol"

        return labels

    def _build_summary(
        self,
        brinson_result: BrinsonResult | None,
        factor_result: FactorAttributionResult | None,
        regime_result: RegimeAttributionResult | None,
        trade_result: TradeAttributionResult | None,
        context: AttributionContext,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {}

        if context.portfolio_returns is not None and len(context.portfolio_returns) > 0:
            pr = context.portfolio_returns.dropna()
            if len(pr) > 0:
                cum_ret = float(np.prod(1 + pr) - 1)
                ann_vol = float(pr.std() * np.sqrt(252))
                sharpe = (
                    float(pr.mean() / pr.std() * np.sqrt(252))
                    if pr.std() > 1e-12
                    else 0.0
                )
                summary["portfolio_cumulative_return"] = round(cum_ret, 6)
                summary["annualized_volatility"] = round(ann_vol, 6)
                summary["sharpe_ratio"] = round(sharpe, 4)

        if brinson_result is not None:
            summary["excess_return"] = brinson_result.total_excess
            summary["allocation_effect"] = brinson_result.allocation_effect
            summary["selection_effect"] = brinson_result.selection_effect
            summary["interaction_effect"] = brinson_result.interaction_effect

        if factor_result is not None:
            summary["factor_r_squared"] = factor_result.r_squared
            summary["specific_return"] = factor_result.specific_return
            top_factor = max(
                factor_result.factor_contributions,
                key=factor_result.factor_contributions.get,
            ) if factor_result.factor_contributions else ""
            summary["top_factor"] = top_factor
            summary["top_factor_contribution"] = factor_result.factor_contributions.get(
                top_factor, 0.0
            )

        if regime_result is not None:
            summary["dominant_regime"] = regime_result.dominant_regime
            if regime_result.dominant_regime in regime_result.regime_breakdown:
                dom = regime_result.regime_breakdown[regime_result.dominant_regime]
                summary["dominant_regime_contribution"] = dom.get("contribution", 0.0)

        if trade_result is not None:
            summary["total_trade_pnl"] = trade_result.total_pnl
            summary["holding_pnl"] = trade_result.holding_pnl
            summary["timing_pnl"] = trade_result.timing_pnl
            summary["total_friction_cost"] = trade_result.friction_cost
            n_trades = len(trade_result.trade_breakdown)
            summary["trade_count"] = n_trades
            if n_trades > 0:
                summary["avg_friction_per_trade"] = round(
                    trade_result.friction_cost / n_trades, 6
                )

        return summary
