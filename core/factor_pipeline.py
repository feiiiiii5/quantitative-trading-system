__all__ = [
    "winsorize",
    "winsorize_df",
    "zscore_normalize",
    "zscore_normalize_df",
    "rank_normalize",
    "rank_normalize_df",
    "industry_neutralize",
    "market_cap_neutralize",
    "orthogonalize",
    "full_factor_pipeline",
    "FactorNode",
    "FactorDAG",
    "DataHandler",
]

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def winsorize(series: pd.Series, lower: float = 0.025, upper: float = 0.975) -> pd.Series:
    clipped = series.copy()
    valid = clipped.dropna()
    if len(valid) < 3:
        return clipped
    q_low = float(valid.quantile(lower))
    q_high = float(valid.quantile(upper))
    clipped = clipped.clip(lower=q_low, upper=q_high)
    return clipped


def winsorize_df(df: pd.DataFrame, lower: float = 0.025, upper: float = 0.975) -> pd.DataFrame:
    return df.apply(lambda col: winsorize(col, lower, upper) if np.issubdtype(col.dtype, np.number) else col)


def zscore_normalize(series: pd.Series) -> pd.Series:
    valid = series.dropna()
    if len(valid) < 2:
        return series.copy()
    mean = float(valid.mean())
    std = float(valid.std())
    if std < 1e-12:
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def zscore_normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.apply(lambda col: zscore_normalize(col) if np.issubdtype(col.dtype, np.number) else col)


def rank_normalize(series: pd.Series) -> pd.Series:
    valid_mask = series.notna()
    ranked = series.copy().astype(float)
    if valid_mask.sum() < 2:
        return ranked
    ranked[valid_mask] = series[valid_mask].rank(pct=True)
    return ranked


def rank_normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.apply(lambda col: rank_normalize(col) if np.issubdtype(col.dtype, np.number) else col)


def industry_neutralize(
    factor_series: pd.Series,
    industry_labels: pd.Series,
) -> pd.Series:
    if len(factor_series) != len(industry_labels):
        logger.warning("factor_series and industry_labels length mismatch")
        return factor_series.copy()
    result = factor_series.copy()
    groups = industry_labels.groupby(industry_labels)
    for _name, idx in groups.groups.items():
        if len(idx) < 2:
            continue
        group_vals = factor_series.loc[idx]
        mean_val = group_vals.mean()
        if group_vals.std() < 1e-12:
            result.loc[idx] = 0.0
        else:
            result.loc[idx] = group_vals - mean_val
    return result


def market_cap_neutralize(
    factor_series: pd.Series,
    market_cap: pd.Series,
) -> pd.Series:
    valid = factor_series.notna() & market_cap.notna() & (market_cap > 0)
    if valid.sum() < 5:
        return factor_series.copy()
    result = factor_series.copy()
    log_mc = np.log(market_cap[valid])
    x = log_mc.values
    y = factor_series[valid].values
    x_mean = x.mean()
    y_mean = y.mean()
    denom = np.sum((x - x_mean) ** 2)
    if denom < 1e-12:
        return result
    beta = np.sum((x - x_mean) * (y - y_mean)) / denom
    alpha = y_mean - beta * x_mean
    residuals = y - (alpha + beta * x)
    result[valid] = residuals
    return result


def orthogonalize(
    factor_df: pd.DataFrame,
    reference_col: str | None = None,
) -> pd.DataFrame:
    if factor_df.empty or len(factor_df.columns) < 2:
        return factor_df.copy()
    result = factor_df.copy()
    numeric_cols = [c for c in result.columns if np.issubdtype(result[c].dtype, np.number)]
    if len(numeric_cols) < 2:
        return result

    if reference_col is None:
        reference_col = numeric_cols[0]
    if reference_col not in numeric_cols:
        return result

    ref = result[reference_col].fillna(0).values
    ref_mean = ref.mean()
    ref_centered = ref - ref_mean
    ref_ss = np.dot(ref_centered, ref_centered)
    if ref_ss < 1e-12:
        return result

    for col in numeric_cols:
        if col == reference_col:
            continue
        target = result[col].fillna(0).values
        target_mean = target.mean()
        target_centered = target - target_mean
        proj = np.dot(target_centered, ref_centered) / ref_ss
        orthogonalized = target - proj * ref_centered
        result[col] = orthogonalized
    return result


def full_factor_pipeline(
    factor_df: pd.DataFrame,
    industry_labels: pd.Series | None = None,
    market_cap: pd.Series | None = None,
    winsorize_bounds: tuple[float, float] = (0.025, 0.975),
    neutralize_method: str = "zscore",
) -> pd.DataFrame:
    if factor_df.empty:
        return factor_df

    result = factor_df.copy()
    numeric_cols = [c for c in result.columns if np.issubdtype(result[c].dtype, np.number)]

    for col in numeric_cols:
        result[col] = winsorize(result[col], winsorize_bounds[0], winsorize_bounds[1])

    if neutralize_method == "zscore":
        for col in numeric_cols:
            result[col] = zscore_normalize(result[col])
    elif neutralize_method == "rank":
        for col in numeric_cols:
            result[col] = rank_normalize(result[col])

    if industry_labels is not None:
        for col in numeric_cols:
            result[col] = industry_neutralize(result[col], industry_labels)

    if market_cap is not None:
        for col in numeric_cols:
            result[col] = market_cap_neutralize(result[col], market_cap)

    if len(numeric_cols) >= 2:
        result = orthogonalize(result, numeric_cols[0])

    return result


@dataclass
class FactorNode:
    name: str
    compute_fn: Any
    dependencies: list[str] = field(default_factory=list)
    category: str = ""
    description: str = ""
    _cache: pd.Series | None = field(default=None, repr=False)

    def is_ready(self, computed: set[str]) -> bool:
        return all(dep in computed for dep in self.dependencies)

    def compute(self, df: pd.DataFrame, cache: dict[str, pd.Series] | None = None) -> pd.Series:
        if self._cache is not None:
            return self._cache
        try:
            result = self.compute_fn(df, cache) if cache and self.dependencies else self.compute_fn(df)
            if isinstance(result, pd.Series):
                self._cache = result
            return result
        except Exception as e:
            logger.debug("FactorNode %s compute failed: %s", self.name, e)
            return pd.Series(dtype=float)

    def invalidate(self) -> None:
        self._cache = None


class FactorDAG:
    def __init__(self):
        self._nodes: dict[str, FactorNode] = {}
        self._execution_order: list[str] = []

    def add_node(self, node: FactorNode) -> None:
        self._nodes[node.name] = node
        self._execution_order = []

    def remove_node(self, name: str) -> None:
        self._nodes.pop(name, None)
        self._execution_order = []

    def get_node(self, name: str) -> FactorNode | None:
        return self._nodes.get(name)

    def _topological_sort(self) -> list[str]:
        in_degree: dict[str, int] = defaultdict(int)
        for name, node in self._nodes.items():
            if name not in in_degree:
                in_degree[name] = 0
            for dep in node.dependencies:
                if dep in self._nodes:
                    in_degree[name] += 1
                else:
                    logger.warning("FactorDAG: node '%s' depends on '%s' which is not in the graph", name, dep)

        queue = [name for name, deg in in_degree.items() if deg == 0]
        order: list[str] = []

        while queue:
            current = queue.pop(0)
            order.append(current)
            for name, node in self._nodes.items():
                if current in node.dependencies:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        if len(order) != len(self._nodes):
            missing = set(self._nodes.keys()) - set(order)
            logger.warning("FactorDAG cycle detected, missing nodes: %s", missing)
            for name in self._nodes:
                if name not in order:
                    order.append(name)

        return order

    def get_execution_order(self) -> list[str]:
        if not self._execution_order:
            self._execution_order = self._topological_sort()
        return list(self._execution_order)

    def execute(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        order = self.get_execution_order()
        cache: dict[str, pd.Series] = {}
        computed: set[str] = set()

        for name in order:
            node = self._nodes[name]
            if node.is_ready(computed):
                result = node.compute(df, cache)
                if isinstance(result, pd.Series) and result.notna().sum() > 0:
                    cache[name] = result
                    computed.add(name)
            else:
                missing_deps = [d for d in node.dependencies if d not in computed]
                logger.debug("Skipping %s: missing deps %s", name, missing_deps)

        return cache

    def invalidate_all(self) -> None:
        for node in self._nodes.values():
            node.invalidate()
        self._execution_order = []

    def visualize(self) -> str:
        order = self.get_execution_order()
        lines = ["FactorDAG Execution Order:"]
        for i, name in enumerate(order):
            node = self._nodes[name]
            deps = ", ".join(node.dependencies) if node.dependencies else "(root)"
            lines.append(f"  {i + 1}. {name} [{node.category}] <- {deps}")
        return "\n".join(lines)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def root_nodes(self) -> list[str]:
        return [name for name, node in self._nodes.items() if not node.dependencies]


class DataHandler:
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._dag = FactorDAG()
        self._pipeline_steps: list[dict[str, Any]] = []
        self._setup_default_pipeline()

    def _setup_default_pipeline(self) -> None:
        self._pipeline_steps = [
            {"name": "winsorize", "fn": winsorize_df, "order": 1},
            {"name": "normalize", "fn": zscore_normalize_df, "order": 2},
            {"name": "neutralize", "fn": None, "order": 3},
            {"name": "orthogonalize", "fn": orthogonalize, "order": 4},
        ]

    def add_factor(
        self,
        name: str,
        compute_fn: Any,
        dependencies: list[str] | None = None,
        category: str = "",
        description: str = "",
    ) -> None:
        node = FactorNode(
            name=name,
            compute_fn=compute_fn,
            dependencies=dependencies or [],
            category=category,
            description=description,
        )
        self._dag.add_node(node)

    def remove_factor(self, name: str) -> None:
        self._dag.remove_node(name)

    def process(
        self,
        df: pd.DataFrame,
        industry_labels: pd.Series | None = None,
        market_cap: pd.Series | None = None,
        winsorize_bounds: tuple[float, float] = (0.025, 0.975),
        neutralize_method: str = "zscore",
    ) -> pd.DataFrame:
        if df.empty:
            return df

        factor_results = self._dag.execute(df)

        if not factor_results:
            return full_factor_pipeline(
                df, industry_labels, market_cap,
                winsorize_bounds, neutralize_method,
            )

        factor_df = pd.DataFrame(factor_results)

        for col in factor_df.columns:
            if np.issubdtype(factor_df[col].dtype, np.number):
                factor_df[col] = winsorize(factor_df[col], winsorize_bounds[0], winsorize_bounds[1])

        if neutralize_method == "zscore":
            for col in factor_df.columns:
                if np.issubdtype(factor_df[col].dtype, np.number):
                    factor_df[col] = zscore_normalize(factor_df[col])
        elif neutralize_method == "rank":
            for col in factor_df.columns:
                if np.issubdtype(factor_df[col].dtype, np.number):
                    factor_df[col] = rank_normalize(factor_df[col])

        if industry_labels is not None:
            for col in factor_df.columns:
                if np.issubdtype(factor_df[col].dtype, np.number):
                    factor_df[col] = industry_neutralize(factor_df[col], industry_labels)

        if market_cap is not None:
            for col in factor_df.columns:
                if np.issubdtype(factor_df[col].dtype, np.number):
                    factor_df[col] = market_cap_neutralize(factor_df[col], market_cap)

        numeric_cols = [c for c in factor_df.columns if np.issubdtype(factor_df[c].dtype, np.number)]
        if len(numeric_cols) >= 2:
            factor_df = orthogonalize(factor_df, numeric_cols[0])

        return factor_df

    def get_execution_order(self) -> list[str]:
        return self._dag.get_execution_order()

    def visualize_dag(self) -> str:
        return self._dag.visualize()

    def invalidate_cache(self) -> None:
        self._dag.invalidate_all()

    @property
    def dag(self) -> FactorDAG:
        return self._dag
