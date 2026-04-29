import logging
import datetime
import numpy as np
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        max_concentration: float = 0.3,
        max_daily_loss: float = 0.05,
        initial_capital: float = 1000000,
    ):
        self._max_concentration = max_concentration
        self._max_daily_loss = max_daily_loss
        self._initial_capital = initial_capital
        self._circuit_breaker_time: Optional[datetime.datetime] = None
        self._daily_pnl: float = 0.0
        self._daily_reset_date: Optional[str] = None
        self._position_returns: Dict[str, List[float]] = {}

    def check_order(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        current_positions: dict,
        total_assets: float,
    ) -> Dict[str, object]:
        if total_assets <= 0:
            return {"approved": False, "reason": "总资产为零或负值"}

        today_str = datetime.date.today().isoformat()
        if self._daily_reset_date != today_str:
            self._daily_pnl = 0.0
            self._daily_reset_date = today_str
            self._circuit_breaker_time = None

        if self._circuit_breaker_time is not None:
            return {"approved": False, "reason": f"日内熔断中，熔断时间: {self._circuit_breaker_time.isoformat()}"}

        if self._daily_pnl < -self._initial_capital * self._max_daily_loss:
            self._circuit_breaker_time = datetime.datetime.now()
            logger.warning(f"日内亏损熔断触发，亏损: {self._daily_pnl:.2f}")
            return {"approved": False, "reason": f"日内亏损超过{self._max_daily_loss * 100:.0f}%，触发熔断"}

        if action == "buy":
            order_value = shares * price
            current_value = current_positions.get(symbol, {}).get("market_value", 0)
            new_value = current_value + order_value
            concentration = new_value / total_assets
            if concentration > self._max_concentration:
                return {
                    "approved": False,
                    "reason": f"持仓集中度{concentration:.1%}超过上限{self._max_concentration:.1%}",
                }

        return {"approved": True, "reason": ""}

    def update_daily_pnl(self, pnl: float):
        today_str = datetime.date.today().isoformat()
        if self._daily_reset_date != today_str:
            self._daily_pnl = 0.0
            self._daily_reset_date = today_str
            self._circuit_breaker_time = None
        self._daily_pnl += pnl
        if self._daily_pnl < -self._initial_capital * self._max_daily_loss and self._circuit_breaker_time is None:
            self._circuit_breaker_time = datetime.datetime.now()
            logger.warning(f"日内亏损熔断触发，亏损: {self._daily_pnl:.2f}")

    def calc_var(self, returns_history: List[float], portfolio_value: float) -> float:
        if len(returns_history) < 20:
            return 0.0
        arr = np.array(returns_history[-20:])
        var_5pct = np.percentile(arr, 5)
        return abs(var_5pct * portfolio_value)

    def update_position_returns(self, symbol: str, daily_return: float):
        if symbol not in self._position_returns:
            self._position_returns[symbol] = []
        self._position_returns[symbol].append(daily_return)

    def get_risk_report(self) -> Dict[str, object]:
        today_str = datetime.date.today().isoformat()
        if self._daily_reset_date != today_str:
            self._daily_pnl = 0.0
            self._daily_reset_date = today_str
            self._circuit_breaker_time = None

        return {
            "max_concentration": self._max_concentration,
            "current_daily_pnl": self._daily_pnl,
            "daily_loss_limit": self._initial_capital * self._max_daily_loss,
            "circuit_breaker_active": self._circuit_breaker_time is not None,
            "circuit_breaker_time": self._circuit_breaker_time.isoformat() if self._circuit_breaker_time else None,
            "var": 0.0,
        }
