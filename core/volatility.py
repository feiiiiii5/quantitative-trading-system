import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def fit_garch(returns: np.ndarray, iterations: int = 5) -> dict[str, Any]:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 30:
        return {"error": "Insufficient data for GARCH fitting (need 30+ observations)"}

    unconditional_var = np.var(r)
    alpha = 0.1
    beta = 0.85
    omega = unconditional_var * (1 - alpha - beta) if (1 - alpha - beta) > 0 else unconditional_var * 0.05
    omega = max(omega, 1e-10)

    n = len(r)
    sigma2 = np.zeros(n)
    sigma2[0] = unconditional_var

    for _ in range(iterations):
        for t in range(1, n):
            sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
            if sigma2[t] < 1e-12 or not np.isfinite(sigma2[t]):
                sigma2[t] = omega / (1 - alpha - beta) if (1 - alpha - beta) > 0 else np.var(r)
        num_omega = np.mean(sigma2[1:] - alpha * r[:-1] ** 2 - beta * sigma2[:-1])
        omega = max(num_omega, 1e-10) if np.isfinite(num_omega) else 1e-10
        denom_alpha = max(np.mean(r[:-1] ** 2 * sigma2[:-1]), 1e-12)
        num_alpha = np.mean(r[:-1] ** 2 * (sigma2[1:] - omega - beta * sigma2[:-1])) / denom_alpha
        alpha = max(0.01, min(0.3, num_alpha)) if np.isfinite(num_alpha) else 0.1
        denom_beta = max(np.mean(sigma2[:-1] ** 2), 1e-12)
        num_beta = np.mean(sigma2[:-1] * (sigma2[1:] - omega - alpha * r[:-1] ** 2)) / denom_beta
        beta = max(0.5, min(0.95, num_beta)) if np.isfinite(num_beta) else 0.85
        if alpha + beta >= 1.0:
            beta = 0.99 - alpha

    persistence = alpha + beta
    long_run_var = omega / (1 - persistence) if persistence < 1 else sigma2[-1]
    if not np.isfinite(long_run_var) or long_run_var < 0:
        long_run_var = np.var(r)
    current_vol = np.sqrt(max(sigma2[-1], 0)) * np.sqrt(252)
    long_run_vol = np.sqrt(max(long_run_var, 0)) * np.sqrt(252)

    forecasts = []
    h = sigma2[-1]
    mean_return = np.mean(r[-22:]) if len(r) >= 22 else np.mean(r)
    for d in range(1, 23):
        h = omega + alpha * mean_return ** 2 + beta * h
        forecasts.append({
            "day": d,
            "volatility_annualized": round(np.sqrt(h) * np.sqrt(252), 4),
        })

    volatility_series = []
    step = max(1, len(sigma2) // 60)
    for i in range(0, len(sigma2), step):
        vol_val = np.sqrt(sigma2[i]) * np.sqrt(252)
        volatility_series.append(round(float(vol_val), 4))

    return {
        "current_volatility": round(float(current_vol), 4),
        "long_run_volatility": round(float(long_run_vol), 4),
        "persistence": round(float(persistence), 4),
        "omega": round(float(omega), 8),
        "alpha": round(float(alpha), 4),
        "beta": round(float(beta), 4),
        "forecast_5d": round(float(forecasts[4]["volatility_annualized"]), 4) if len(forecasts) > 4 else None,
        "forecast_10d": round(float(forecasts[9]["volatility_annualized"]), 4) if len(forecasts) > 9 else None,
        "forecast_22d": round(float(forecasts[21]["volatility_annualized"]), 4) if len(forecasts) > 21 else None,
        "forecast_series": forecasts,
        "volatility_history": volatility_series,
        "regime": "HIGH_VOL" if current_vol > long_run_vol * 1.5 else ("LOW_VOL" if current_vol < long_run_vol * 0.7 else "NORMAL"),
    }


def detect_regime_hmm(returns: np.ndarray, n_states: int = 3) -> dict[str, Any]:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 60:
        return {"error": "Insufficient data for HMM regime detection (need 60+ observations)"}

    means = np.linspace(np.percentile(r, 20), np.percentile(r, 80), n_states)
    vols = np.full(n_states, np.std(r))
    weights = np.full(n_states, 1.0 / n_states)

    for _ in range(50):
        resp = np.zeros((len(r), n_states))
        for k in range(n_states):
            diff = r - means[k]
            resp[:, k] = weights[k] * np.exp(-0.5 * diff ** 2 / vols[k] ** 2) / (vols[k] * np.sqrt(2 * np.pi))
        resp_sum = resp.sum(axis=1, keepdims=True)
        resp_sum[resp_sum < 1e-300] = 1e-300
        resp = resp / resp_sum

        nk = resp.sum(axis=0)
        nk[nk < 1e-10] = 1e-10
        for k in range(n_states):
            means[k] = np.sum(resp[:, k] * r) / nk[k]
            vols[k] = max(np.sqrt(np.sum(resp[:, k] * (r - means[k]) ** 2) / nk[k]), 1e-8)
        weights = nk / len(r)

    state_probs = resp[-1]
    current_state = int(np.argmax(state_probs))

    sorted_idx = np.argsort(means)
    label_map = {}
    for rank, orig_idx in enumerate(sorted_idx):
        if rank == 0:
            label_map[orig_idx] = "BEAR"
        elif rank == n_states - 1:
            label_map[orig_idx] = "BULL"
        else:
            label_map[orig_idx] = "NEUTRAL"

    transition_probs = np.zeros((n_states, n_states))
    for t in range(1, len(r)):
        prev_state = int(np.argmax(resp[t - 1]))
        curr_state = int(np.argmax(resp[t]))
        transition_probs[prev_state, curr_state] += 1
    for k in range(n_states):
        row_sum = transition_probs[k].sum()
        if row_sum > 0:
            transition_probs[k] /= row_sum

    regime_history = []
    step = max(1, len(resp) // 60)
    for i in range(0, len(resp), step):
        state = int(np.argmax(resp[i]))
        regime_history.append({
            "index": i,
            "state": state,
            "label": label_map.get(state, "NEUTRAL"),
            "probability": round(float(resp[i, state]), 4),
        })

    return {
        "current_state": current_state,
        "current_label": label_map.get(current_state, "NEUTRAL"),
        "state_probabilities": {label_map.get(k, "NEUTRAL"): round(float(state_probs[k]), 4) for k in range(n_states)},
        "states": [
            {
                "label": label_map.get(k, "NEUTRAL"),
                "mean_daily_return": round(float(means[k]) * 100, 4),
                "annualized_volatility": round(float(vols[k]) * np.sqrt(252) * 100, 2),
                "weight": round(float(weights[k]), 4),
            }
            for k in range(n_states)
        ],
        "transition_matrix": transition_probs.tolist(),
        "regime_history": regime_history,
    }
