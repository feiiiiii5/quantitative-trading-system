import logging

import numpy as np

logger = logging.getLogger(__name__)


class PositionSizer:
    """仓位计算器，支持凯利公式、固定比例、风险平价和ATR止损法"""

    @staticmethod
    def kelly_fraction(
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        fraction: float = 0.5,
    ) -> dict:
        """凯利公式计算最优仓位比例

        Args:
            win_rate: 胜率 (0-1)
            avg_win: 平均盈利比例 (如0.05表示5%)
            avg_loss: 平均亏损比例 (如0.03表示3%)
            fraction: 凯利分数，0.5为半凯利（更保守）

        Returns:
            建议仓位比例和风险指标
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return {
                "error": "参数无效：需要 0 < win_rate < 1 且 avg_loss > 0",
                "suggested_fraction": 0.0,
            }

        # 凯利公式: f* = (p*b - q) / b，其中 b = avg_win/avg_loss
        b = avg_win / avg_loss
        q = 1 - win_rate
        kelly_full = (win_rate * b - q) / b

        # 凯利值为负时不应该下注
        if kelly_full <= 0:
            return {
                "kelly_full": round(kelly_full, 4),
                "suggested_fraction": 0.0,
                "fraction_type": "no_bet",
                "reason": "期望收益为负，不建议建仓",
                "win_rate": round(win_rate, 4),
                "win_loss_ratio": round(b, 4),
            }

        # 使用分数凯利降低波动
        suggested = kelly_full * fraction
        suggested = min(suggested, 0.25)  # 单标的最多25%仓位

        # 计算破产概率（简化模型）
        ruin_prob = (q / (win_rate * b)) ** min(suggested / avg_loss, 100) if (win_rate * b) > q else 1.0
        ruin_prob = min(ruin_prob, 1.0)

        return {
            "kelly_full": round(kelly_full, 4),
            "suggested_fraction": round(suggested, 4),
            "fraction_type": "half_kelly" if fraction == 0.5 else f"{fraction:.0%}_kelly",
            "win_rate": round(win_rate, 4),
            "win_loss_ratio": round(b, 4),
            "expected_value": round(win_rate * avg_win - (1 - win_rate) * avg_loss, 4),
            "ruin_probability": round(ruin_prob, 4),
            "max_position_pct": 25.0,
        }

    @staticmethod
    def atr_position_size(
        capital: float,
        entry_price: float,
        atr: float,
        risk_pct: float = 0.02,
        atr_multiplier: float = 2.0,
    ) -> dict:
        """基于ATR止损的仓位计算

        Args:
            capital: 总资金
            entry_price: 入场价
            atr: 当前ATR值
            risk_pct: 单笔最大风险占总资金比例 (默认2%)
            atr_multiplier: ATR止损倍数 (默认2倍)

        Returns:
            建议股数和止损价位
        """
        if entry_price <= 0 or atr <= 0 or capital <= 0:
            return {"error": "参数必须为正数", "shares": 0}

        # 止损距离 = ATR * 倍数
        stop_distance = atr * atr_multiplier
        stop_price = entry_price - stop_distance

        # 单笔最大亏损金额
        max_loss_amount = capital * risk_pct

        # 每股最大亏损
        loss_per_share = stop_distance

        # 建议股数
        shares = int(max_loss_amount / loss_per_share) if loss_per_share > 0 else 0
        shares = max(shares, 0)

        # 实际仓位比例
        position_value = shares * entry_price
        position_pct = position_value / capital * 100 if capital > 0 else 0

        # 实际风险比例
        actual_risk = shares * loss_per_share / capital * 100 if capital > 0 else 0

        return {
            "shares": shares,
            "stop_price": round(stop_price, 2),
            "position_value": round(position_value, 2),
            "position_pct": round(position_pct, 2),
            "actual_risk_pct": round(actual_risk, 2),
            "stop_distance_pct": round(stop_distance / entry_price * 100, 2),
            "atr_multiplier": atr_multiplier,
        }

    @staticmethod
    def fixed_ratio_size(
        capital: float,
        entry_price: float,
        position_pct: float = 0.1,
        max_position_pct: float = 0.25,
    ) -> dict:
        """固定比例仓位计算

        Args:
            capital: 总资金
            entry_price: 入场价
            position_pct: 目标仓位比例 (默认10%)
            max_position_pct: 最大仓位比例 (默认25%)

        Returns:
            建议股数和仓位信息
        """
        if entry_price <= 0 or capital <= 0:
            return {"error": "参数必须为正数", "shares": 0}

        position_pct = min(position_pct, max_position_pct)
        target_value = capital * position_pct
        shares = int(target_value / entry_price)
        shares = max(shares, 0)

        actual_value = shares * entry_price
        actual_pct = actual_value / capital * 100 if capital > 0 else 0

        return {
            "shares": shares,
            "target_pct": round(position_pct * 100, 2),
            "actual_pct": round(actual_pct, 2),
            "position_value": round(actual_value, 2),
        }

    @staticmethod
    def risk_parity_size(
        capital: float,
        positions: list[dict],
    ) -> dict:
        """风险平价仓位分配

        Args:
            capital: 总资金
            positions: [{"symbol": "xxx", "volatility": 0.25}, ...]

        Returns:
            各标的的建议仓位
        """
        if not positions or capital <= 0:
            return {"error": "参数无效", "allocations": []}

        # 过滤无效数据
        valid = [p for p in positions if p.get("volatility", 0) > 0]
        if not valid:
            return {"error": "所有标的波动率为零", "allocations": []}

        # 风险倒数加权
        inv_vols = [1.0 / p["volatility"] for p in valid]
        total_inv = sum(inv_vols)

        allocations = []
        for i, p in enumerate(valid):
            weight = inv_vols[i] / total_inv
            alloc_capital = capital * weight
            allocations.append({
                "symbol": p["symbol"],
                "weight": round(weight, 4),
                "capital": round(alloc_capital, 2),
                "risk_contribution": round(p["volatility"] * weight, 4),
            })

        # 验证等风险贡献
        risk_contribs = [a["risk_contribution"] for a in allocations]
        risk_balance = float(np.std(risk_contribs) / (np.mean(risk_contribs) + 1e-10))

        return {
            "allocations": allocations,
            "risk_balance_cv": round(risk_balance, 4),
            "total_capital": capital,
        }


_sizer: PositionSizer | None = None


def get_position_sizer() -> PositionSizer:
    global _sizer
    if _sizer is None:
        _sizer = PositionSizer()
    return _sizer
