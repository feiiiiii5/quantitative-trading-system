"""
QuantCore Monte Carlo VaR 模拟模块
使用参数化蒙特卡洛模拟计算投资组合风险值
"""
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloVaRResult:
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    expected_shortfall_95: float
    expected_shortfall_99: float
    mean_portfolio_return: float
    std_portfolio_return: float
    n_simulations: int
    confidence_levels: dict[str, float]
    is_valid: bool
    message: str


class MonteCarloVaR:

    def __init__(
        self,
        n_simulations: int = 10000,
        time_horizon: int = 1,
        risk_free_rate: float = 0.03,
        random_seed: int | None = None,
    ):
        self.n_simulations = n_simulations
        self.time_horizon = time_horizon
        self.risk_free_rate = risk_free_rate
        self.random_seed = random_seed

    def simulate(
        self,
        prices: pd.DataFrame,
        weights: dict[str, float] | None = None,
    ) -> MonteCarloVaRResult:
        """
        Run Monte Carlo VaR simulation.

        Parameters
        ----------
        prices : DataFrame of asset prices
        weights : Optional dict of portfolio weights. Equal weight if None.
        """
        try:
            returns = np.log(prices / prices.shift(1)).dropna()
            if len(returns) < 30:
                return MonteCarloVaRResult(
                    var_95=0.0, var_99=0.0, cvar_95=0.0, cvar_99=0.0,
                    expected_shortfall_95=0.0, expected_shortfall_99=0.0,
                    mean_portfolio_return=0.0, std_portfolio_return=0.0,
                    n_simulations=0, confidence_levels={},
                    is_valid=False,
                    message="Insufficient data, need at least 30 days",
                )

            columns = prices.columns
            n_assets = len(columns)

            if weights is None:
                weights = dict.fromkeys(columns, 1.0 / n_assets)

            w_arr = np.array([weights.get(col, 0.0) for col in columns])
            w_sum = np.sum(w_arr)
            if w_sum > 0:
                w_arr = w_arr / w_sum

            mean_returns = returns.mean().values * 252
            cov_matrix = returns.cov().values * 252

            rng = np.random.default_rng(self.random_seed)

            simulated_returns = rng.multivariate_normal(
                mean_returns, cov_matrix, self.n_simulations
            )

            portfolio_returns = simulated_returns @ w_arr

            daily_mean = np.mean(portfolio_returns) / 252
            daily_std = np.std(portfolio_returns) / np.sqrt(252)
            horizon_returns = daily_mean * self.time_horizon + daily_std * np.sqrt(self.time_horizon) * rng.standard_normal(self.n_simulations)

            var_95 = float(np.percentile(horizon_returns, 5))
            var_99 = float(np.percentile(horizon_returns, 1))
            cvar_95 = float(np.mean(horizon_returns[horizon_returns <= var_95]))
            cvar_99 = float(np.mean(horizon_returns[horizon_returns <= var_99]))

            return MonteCarloVaRResult(
                var_95=var_95,
                var_99=var_99,
                cvar_95=cvar_95,
                cvar_99=cvar_99,
                expected_shortfall_95=cvar_95,
                expected_shortfall_99=cvar_99,
                mean_portfolio_return=float(np.mean(horizon_returns)),
                std_portfolio_return=float(np.std(horizon_returns)),
                n_simulations=self.n_simulations,
                confidence_levels={
                    "95%": round(var_95, 6),
                    "99%": round(var_99, 6),
                },
                is_valid=True,
                message="Monte Carlo VaR simulation successful",
            )
        except Exception as e:
            logger.warning("Monte Carlo VaR simulation failed: %s", e)
            return MonteCarloVaRResult(
                var_95=0.0, var_99=0.0, cvar_95=0.0, cvar_99=0.0,
                expected_shortfall_95=0.0, expected_shortfall_99=0.0,
                mean_portfolio_return=0.0, std_portfolio_return=0.0,
                n_simulations=0, confidence_levels={},
                is_valid=False,
                message=f"Simulation failed: {e}",
            )

    def simulate_historical(
        self,
        prices: pd.DataFrame,
        weights: dict[str, float] | None = None,
    ) -> MonteCarloVaRResult:
        """Historical simulation VaR using bootstrap resampling."""
        try:
            returns = np.log(prices / prices.shift(1)).dropna()
            if len(returns) < 30:
                return MonteCarloVaRResult(
                    var_95=0.0, var_99=0.0, cvar_95=0.0, cvar_99=0.0,
                    expected_shortfall_95=0.0, expected_shortfall_99=0.0,
                    mean_portfolio_return=0.0, std_portfolio_return=0.0,
                    n_simulations=0, confidence_levels={},
                    is_valid=False,
                    message="Insufficient data, need at least 30 days",
                )

            columns = prices.columns
            n_assets = len(columns)

            if weights is None:
                weights = dict.fromkeys(columns, 1.0 / n_assets)

            w_arr = np.array([weights.get(col, 0.0) for col in columns])
            w_sum = np.sum(w_arr)
            if w_sum > 0:
                w_arr = w_arr / w_sum

            portfolio_returns = returns.values @ w_arr

            rng = np.random.default_rng(self.random_seed)
            indices = rng.integers(0, len(portfolio_returns), self.n_simulations)
            sampled_returns = portfolio_returns[indices]

            var_95 = float(np.percentile(sampled_returns, 5))
            var_99 = float(np.percentile(sampled_returns, 1))
            cvar_95 = float(np.mean(sampled_returns[sampled_returns <= var_95]))
            cvar_99 = float(np.mean(sampled_returns[sampled_returns <= var_99]))

            return MonteCarloVaRResult(
                var_95=var_95,
                var_99=var_99,
                cvar_95=cvar_95,
                cvar_99=cvar_99,
                expected_shortfall_95=cvar_95,
                expected_shortfall_99=cvar_99,
                mean_portfolio_return=float(np.mean(sampled_returns)),
                std_portfolio_return=float(np.std(sampled_returns)),
                n_simulations=self.n_simulations,
                confidence_levels={
                    "95%": round(var_95, 6),
                    "99%": round(var_99, 6),
                },
                is_valid=True,
                message="Historical VaR simulation successful",
            )
        except Exception as e:
            logger.warning("Historical VaR simulation failed: %s", e)
            return MonteCarloVaRResult(
                var_95=0.0, var_99=0.0, cvar_95=0.0, cvar_99=0.0,
                expected_shortfall_95=0.0, expected_shortfall_99=0.0,
                mean_portfolio_return=0.0, std_portfolio_return=0.0,
                n_simulations=0, confidence_levels={},
                is_valid=False,
                message=f"Simulation failed: {e}",
            )
