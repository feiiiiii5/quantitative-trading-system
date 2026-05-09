import logging

import numpy as np

logger = logging.getLogger(__name__)


def compute_backtest_statistics(
    equity_curve: list[float],
    closes: np.ndarray,
    trades: list[dict],
    dates_list: list[str],
) -> dict:
    eq_arr = np.array(equity_curve)
    peak_arr = np.maximum.accumulate(eq_arr)
    drawdown_curve = ((peak_arr - eq_arr) / np.where(peak_arr > 1e-9, peak_arr, 1.0) * 100).tolist()
    max_dd = float(np.max(drawdown_curve))

    sell_trades = [t for t in trades if t["action"] == "sell"]
    total_trades = len(sell_trades)
    win_trades = 0
    loss_trades = 0
    total_win = 0.0
    total_loss = 0.0
    win_pnls = []
    loss_pnls = []
    hold_days_list = []
    for t in sell_trades:
        pnl = t.get("pnl", 0)
        if pnl > 0:
            win_trades += 1
            total_win += pnl
            win_pnls.append(pnl)
        elif pnl < 0:
            loss_trades += 1
            total_loss += abs(pnl)
            loss_pnls.append(abs(pnl))
        hd = t.get("hold_days", 0)
        if hd:
            hold_days_list.append(hd)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
    profit_factor = (total_win / total_loss) if total_loss > 0 else (999.0 if total_win > 0 else 0.0)
    avg_profit = float(np.mean(win_pnls)) if win_pnls else 0.0
    avg_loss = float(np.mean(loss_pnls)) if loss_pnls else 0.0
    avg_hold_days = float(np.mean(hold_days_list)) if hold_days_list else 0.0

    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0] * 100 if equity_curve[0] > 1e-9 else 0.0
    trading_days = len(equity_curve)
    if trading_days >= 20:
        annual_return = ((1 + total_return / 100) ** min(252 / trading_days, 3) - 1) * 100
    else:
        annual_return = total_return

    calmar_ratio = (annual_return / max_dd) if max_dd > 1e-9 and annual_return != 0 else 0.0

    returns = []
    eq_arr_full = np.array(equity_curve)
    if len(eq_arr_full) > 1:
        mask = eq_arr_full[:-1] > 0
        ret = np.where(mask, (eq_arr_full[1:] - eq_arr_full[:-1]) / eq_arr_full[:-1], 0)
        returns = ret.tolist()

    sharpe = 0
    if returns:
        avg_ret = np.mean(returns)
        std_ret = np.std(returns)
        if std_ret > 0:
            sharpe = avg_ret / std_ret * np.sqrt(252)

    sortino = 0.0
    if returns:
        ret_arr = np.array(returns)
        avg_ret = np.mean(ret_arr)
        downside = ret_arr[ret_arr < 0]
        if len(downside) > 0:
            downside_dev = np.sqrt(np.mean(downside ** 2))
            if downside_dev > 1e-12:
                sortino = (avg_ret * 252) / (downside_dev * np.sqrt(252))

    max_consec_losses = 0
    consec_count = 0
    for t in sell_trades:
        if t.get("pnl", 0) < 0:
            consec_count += 1
            if consec_count > max_consec_losses:
                max_consec_losses = consec_count
        else:
            consec_count = 0

    benchmark_return = (closes[-1] - closes[0]) / closes[0] * 100 if len(closes) > 0 and closes[0] > 1e-9 else 0.0
    alpha = total_return - benchmark_return

    bench_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            bench_returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

    beta = 1.0
    information_ratio = 0.0
    if len(returns) > 1 and len(bench_returns) > 1:
        min_len = min(len(returns), len(bench_returns))
        r = np.array(returns[:min_len])
        b = np.array(bench_returns[:min_len])
        bench_var = np.var(b)
        if bench_var > 0:
            beta = float(np.cov(r, b)[0][1] / bench_var)
        excess = r - b
        tracking_error = np.std(excess)
        if tracking_error > 0:
            information_ratio = float(np.mean(excess) / tracking_error * np.sqrt(252))

    omega_ratio = 0.0
    tail_ratio = 0.0
    if returns:
        ret_arr = np.array(returns, dtype=float)
        ret_arr = ret_arr[np.isfinite(ret_arr)]
        if len(ret_arr) > 0:
            gains = ret_arr[ret_arr > 0].sum()
            losses = abs(ret_arr[ret_arr < 0].sum())
            if losses > 0:
                omega_ratio = float(gains / losses)
            elif gains > 0:
                omega_ratio = 999.0
            q95 = float(np.percentile(ret_arr, 95))
            q05 = float(np.percentile(ret_arr, 5))
            tail_ratio = abs(q95 / q05) if abs(q05) > 1e-09 else 0.0

    recovery_factor = (total_return / max_dd) if max_dd > 1e-9 else 0.0
    avg_mae = np.mean([abs(t.get("mae", 0)) for t in sell_trades]) if sell_trades else 0.0
    avg_mfe = np.mean([t.get("mfe", 0) for t in sell_trades]) if sell_trades else 0.0
    win_rate_frac = win_trades / total_trades if total_trades > 0 else 0.0
    loss_rate_frac = loss_trades / total_trades if total_trades > 0 else 0.0
    expectancy = win_rate_frac * avg_profit - loss_rate_frac * avg_loss
    payoff_ratio = (avg_profit / avg_loss) if avg_loss > 1e-9 else (999.0 if avg_profit > 0 else 0.0)

    cvar_95 = 0.0
    var_95 = 0.0
    annual_vol = 0.0
    downside_dev_val = 0.0
    monthly_rets = []
    if returns:
        ret_arr = np.array(returns, dtype=float)
        ret_arr = ret_arr[np.isfinite(ret_arr)]
        if len(ret_arr) > 1:
            annual_vol = float(np.std(ret_arr) * np.sqrt(252))
            neg_rets = ret_arr[ret_arr < 0]
            if len(neg_rets) > 0:
                downside_dev_val = float(np.std(neg_rets) * np.sqrt(252))
            var_5 = float(np.percentile(ret_arr, 5))
            var_95 = -var_5
            tail_5 = ret_arr[ret_arr <= var_5]
            if len(tail_5) > 0:
                cvar_95 = float(-np.mean(tail_5))
    if len(dates_list) > 20 and len(equity_curve) > 20:
        try:
            eq_arr_local = np.array(equity_curve, dtype=float)
            eq_dates = list(dates_list)
            monthly_map: dict[str, list[float]] = {}
            for j in range(1, len(eq_arr_local)):
                if j >= len(eq_dates):
                    break
                d = str(eq_dates[j])[:7]
                if d not in monthly_map:
                    monthly_map[d] = []
                if eq_arr_local[j - 1] > 0:
                    monthly_map[d].append((eq_arr_local[j] / eq_arr_local[j - 1]) - 1)
            for m in sorted(monthly_map.keys()):
                vals = monthly_map[m]
                if vals:
                    monthly_rets.append({"month": m, "return": float(np.mean(vals))})
        except Exception as e:
            logger.debug("Monthly return calculation failed: %s", e)

    return {
        "total_return": round(total_return, 2),
        "annual_return": round(annual_return, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 2),
        "calmar_ratio": round(calmar_ratio, 2),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != 999 else 999,
        "total_trades": total_trades,
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "avg_profit": round(avg_profit, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_hold_days": round(avg_hold_days, 1),
        "benchmark_return": round(benchmark_return, 2),
        "alpha": round(alpha, 2),
        "beta": round(beta, 2),
        "drawdown_curve": drawdown_curve,
        "sortino_ratio": round(sortino, 2),
        "max_consecutive_losses": max_consec_losses,
        "omega_ratio": round(omega_ratio, 2) if omega_ratio != 999.0 else 999.0,
        "tail_ratio": round(tail_ratio, 2),
        "information_ratio": round(information_ratio, 2),
        "recovery_factor": round(recovery_factor, 2),
        "avg_mae": round(float(avg_mae), 2),
        "avg_mfe": round(float(avg_mfe), 2),
        "cvar_95": round(cvar_95, 4),
        "var_95": round(var_95, 4),
        "annual_volatility": round(annual_vol, 4),
        "downside_deviation": round(downside_dev_val, 4),
        "monthly_returns": monthly_rets,
        "expectancy": round(float(expectancy), 2),
        "payoff_ratio": round(float(payoff_ratio), 2) if payoff_ratio != 999 else 999,
    }
