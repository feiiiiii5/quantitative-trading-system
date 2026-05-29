__all__ = [
    "CrossSectionalRanker",
    "LGBM_AVAILABLE",
]

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import lightgbm as lgb

    LGBM_AVAILABLE = True
except ImportError:
    lgb = None
    LGBM_AVAILABLE = False


@dataclass
class RankerConfig:
    objective: str = "regression"
    num_leaves: int = 31
    learning_rate: float = 0.05
    feature_fraction: float = 0.7
    bagging_fraction: float = 0.8
    bagging_freq: int = 5
    min_data_in_leaf: int = 50
    lambda_l1: float = 0.1
    lambda_l2: float = 0.1
    num_boost_round: int = 200
    early_stopping_rounds: int = 20
    verbose: int = -1


class CrossSectionalRanker:
    def __init__(self, config: RankerConfig | None = None):
        self._config = config or RankerConfig()
        self._model: Any = None
        self._feature_names: list[str] = []
        self._is_fitted = False
        self._train_info: dict[str, Any] = {}

    def fit(
        self,
        factor_matrix: pd.DataFrame,
        forward_returns: pd.Series,
        val_ratio: float = 0.2,
    ) -> dict[str, Any]:
        if not LGBM_AVAILABLE:
            raise ImportError("lightgbm is required for CrossSectionalRanker. Install with: pip install lightgbm")

        valid_mask = factor_matrix.notna().all(axis=1) & forward_returns.notna()
        X = factor_matrix[valid_mask].copy()  # noqa: N806
        y = forward_returns[valid_mask].copy()

        if len(X) < self._config.min_data_in_leaf * 2:
            raise ValueError(f"Insufficient data: {len(X)} rows, need at least {self._config.min_data_in_leaf * 2}")

        self._feature_names = X.columns.tolist()
        labels = y.rank(pct=True).values

        n_val = max(1, int(len(X) * val_ratio))
        X_train, X_val = X.iloc[:-n_val], X.iloc[-n_val:]  # noqa: N806
        y_train, y_val = labels[:-n_val], labels[-n_val:]

        train_data = lgb.Dataset(
            X_train.values,
            label=y_train,
            feature_name=self._feature_names,
        )
        val_data = lgb.Dataset(
            X_val.values,
            label=y_val,
            feature_name=self._feature_names,
            reference=train_data,
        )

        params = {
            "objective": self._config.objective,
            "num_leaves": self._config.num_leaves,
            "learning_rate": self._config.learning_rate,
            "feature_fraction": self._config.feature_fraction,
            "bagging_fraction": self._config.bagging_fraction,
            "bagging_freq": self._config.bagging_freq,
            "min_data_in_leaf": self._config.min_data_in_leaf,
            "lambda_l1": self._config.lambda_l1,
            "lambda_l2": self._config.lambda_l2,
            "verbose": self._config.verbose,
        }

        callbacks = [lgb.early_stopping(self._config.early_stopping_rounds, verbose=False)] if val_ratio > 0 else []

        self._model = lgb.train(
            params,
            train_data,
            num_boost_round=self._config.num_boost_round,
            valid_sets=[val_data] if val_ratio > 0 else None,
            callbacks=callbacks,
        )

        self._is_fitted = True
        self._train_info = {
            "n_samples": len(X),
            "n_train": len(X_train),
            "n_val": len(X_val),
            "best_iteration": self._model.best_iteration if hasattr(self._model, "best_iteration") else self._config.num_boost_round,
            "feature_names": self._feature_names,
        }

        return self._train_info

    def predict(self, factor_matrix: pd.DataFrame) -> pd.Series:
        if not self._is_fitted:
            raise RuntimeError("Model not fitted yet. Call fit() first.")

        X = factor_matrix.reindex(columns=self._feature_names, fill_value=0)  # noqa: N806
        X = X.fillna(0)  # noqa: N806
        raw_scores = self._model.predict(X.values)
        ranked = pd.Series(raw_scores, index=factor_matrix.index).rank(pct=True)
        return ranked

    def predict_raw(self, factor_matrix: pd.DataFrame) -> pd.Series:
        if not self._is_fitted:
            raise RuntimeError("Model not fitted yet. Call fit() first.")

        X = factor_matrix.reindex(columns=self._feature_names, fill_value=0)  # noqa: N806
        X = X.fillna(0)  # noqa: N806
        return pd.Series(self._model.predict(X.values), index=factor_matrix.index)

    def feature_importance(self, importance_type: str = "gain") -> pd.Series:
        if not self._is_fitted:
            return pd.Series(dtype=float)
        importance = self._model.feature_importance(importance_type=importance_type)
        return pd.Series(importance, index=self._feature_names).sort_values(ascending=False)

    def select_top_stocks(
        self,
        factor_matrix: pd.DataFrame,
        n_stocks: int = 10,
    ) -> list[str]:
        ranked = self.predict(factor_matrix)
        return ranked.nlargest(n_stocks).index.tolist()

    def save_model(self, path: str | Path) -> None:
        if not self._is_fitted:
            raise RuntimeError("Model not fitted yet.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path))

    def load_model(self, path: str | Path) -> None:
        if not LGBM_AVAILABLE:
            raise ImportError("lightgbm is required")
        self._model = lgb.Booster(model_file=str(path))
        self._is_fitted = True
        self._feature_names = self._model.feature_name()

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    @property
    def train_info(self) -> dict[str, Any]:
        return dict(self._train_info)
