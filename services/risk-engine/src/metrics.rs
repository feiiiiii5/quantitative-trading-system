use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskMetrics {
    pub var_95: f64,
    pub var_99: f64,
    pub cvar_95: f64,
    pub max_drawdown: f64,
    pub sharpe_ratio: f64,
    pub sortino_ratio: f64,
    pub beta: f64,
    pub correlation: f64,
    pub leverage: f64,
    pub gross_exposure: f64,
    pub net_exposure: f64,
}

impl Default for RiskMetrics {
    fn default() -> Self {
        Self {
            var_95: 0.0,
            var_99: 0.0,
            cvar_95: 0.0,
            max_drawdown: 0.0,
            sharpe_ratio: 0.0,
            sortino_ratio: 0.0,
            beta: 0.0,
            correlation: 0.0,
            leverage: 0.0,
            gross_exposure: 0.0,
            net_exposure: 0.0,
        }
    }
}

pub fn calculate_var(returns: &[f64], confidence: f64) -> f64 {
    if returns.is_empty() {
        return 0.0;
    }

    let mut sorted = returns.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let alpha = 1.0 - confidence;
    let idx = ((alpha * sorted.len() as f64).floor()) as usize;
    let idx = idx.min(sorted.len() - 1);

    -sorted[idx]
}

pub fn calculate_cvar(returns: &[f64], confidence: f64) -> f64 {
    if returns.is_empty() {
        return 0.0;
    }

    let mut sorted = returns.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let alpha = 1.0 - confidence;
    let tail_count = ((alpha * sorted.len() as f64).ceil()) as usize;
    let tail_count = tail_count.max(1).min(sorted.len());

    let tail_sum: f64 = sorted[..tail_count].iter().sum();
    -tail_sum / tail_count as f64
}

pub fn calculate_max_drawdown(equity_curve: &[f64]) -> f64 {
    if equity_curve.is_empty() {
        return 0.0;
    }

    let mut peak = equity_curve[0];
    let mut max_dd = 0.0_f64;

    for &value in equity_curve {
        if value > peak {
            peak = value;
        }
        if peak > 0.0 {
            let dd = (peak - value) / peak;
            if dd > max_dd {
                max_dd = dd;
            }
        }
    }

    max_dd
}

pub fn calculate_sharpe(returns: &[f64], risk_free_rate: f64) -> f64 {
    if returns.is_empty() {
        return 0.0;
    }

    let n = returns.len() as f64;
    let mean: f64 = returns.iter().sum::<f64>() / n;

    let variance: f64 =
        returns.iter().map(|r| (r - mean).powi(2)).sum::<f64>() / n;

    let std_dev = variance.sqrt();

    if std_dev < 1e-12 {
        return 0.0;
    }

    (mean - risk_free_rate) / std_dev
}

pub fn calculate_sortino(returns: &[f64], risk_free_rate: f64) -> f64 {
    if returns.is_empty() {
        return 0.0;
    }

    let n = returns.len() as f64;
    let mean: f64 = returns.iter().sum::<f64>() / n;

    let downside_variance: f64 = returns
        .iter()
        .map(|r| {
            let target = risk_free_rate;
            if *r < target {
                (r - target).powi(2)
            } else {
                0.0
            }
        })
        .sum::<f64>()
        / n;

    let downside_dev = downside_variance.sqrt();

    if downside_dev < 1e-12 {
        return 0.0;
    }

    (mean - risk_free_rate) / downside_dev
}

pub fn calculate_beta(returns: &[f64], benchmark_returns: &[f64]) -> f64 {
    if returns.is_empty() || benchmark_returns.is_empty() || returns.len() != benchmark_returns.len() {
        return 0.0;
    }

    let n = returns.len() as f64;
    let mean_r: f64 = returns.iter().sum::<f64>() / n;
    let mean_b: f64 = benchmark_returns.iter().sum::<f64>() / n;

    let covariance: f64 = returns
        .iter()
        .zip(benchmark_returns.iter())
        .map(|(r, b)| (r - mean_r) * (b - mean_b))
        .sum::<f64>()
        / n;

    let benchmark_variance: f64 = benchmark_returns
        .iter()
        .map(|b| (b - mean_b).powi(2))
        .sum::<f64>()
        / n;

    if benchmark_variance < 1e-12 {
        return 0.0;
    }

    covariance / benchmark_variance
}

pub fn calculate_correlation(returns: &[f64], benchmark_returns: &[f64]) -> f64 {
    if returns.is_empty() || benchmark_returns.is_empty() || returns.len() != benchmark_returns.len() {
        return 0.0;
    }

    let n = returns.len() as f64;
    let mean_r: f64 = returns.iter().sum::<f64>() / n;
    let mean_b: f64 = benchmark_returns.iter().sum::<f64>() / n;

    let covariance: f64 = returns
        .iter()
        .zip(benchmark_returns.iter())
        .map(|(r, b)| (r - mean_r) * (b - mean_b))
        .sum::<f64>()
        / n;

    let std_r: f64 = (returns.iter().map(|r| (r - mean_r).powi(2)).sum::<f64>() / n).sqrt();
    let std_b: f64 = (benchmark_returns
        .iter()
        .map(|b| (b - mean_b).powi(2))
        .sum::<f64>()
        / n)
        .sqrt();

    if std_r < 1e-12 || std_b < 1e-12 {
        return 0.0;
    }

    covariance / (std_r * std_b)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn var_95_basic() {
        let returns: Vec<f64> = (-50..=50).map(|i| i as f64 / 1000.0).collect();
        let var = calculate_var(&returns, 0.95);
        assert!(var > 0.0, "VaR should be positive for symmetric returns");
    }

    #[test]
    fn var_empty_returns() {
        assert_eq!(calculate_var(&[], 0.95), 0.0);
    }

    #[test]
    fn cvar_exceeds_var() {
        let returns: Vec<f64> = (-50..=50).map(|i| i as f64 / 1000.0).collect();
        let var = calculate_var(&returns, 0.95);
        let cvar = calculate_cvar(&returns, 0.95);
        assert!(cvar >= var, "CVaR should be >= VaR");
    }

    #[test]
    fn max_drawdown_monotonic_increase() {
        let curve = vec![100.0, 110.0, 120.0, 130.0];
        assert_eq!(calculate_max_drawdown(&curve), 0.0);
    }

    #[test]
    fn max_drawdown_with_dip() {
        let curve = vec![100.0, 120.0, 90.0, 110.0];
        let dd = calculate_max_drawdown(&curve);
        assert!((dd - 0.25).abs() < 1e-9);
    }

    #[test]
    fn sharpe_positive_for_positive_returns() {
        let returns = vec![0.01, 0.02, 0.015, 0.01, 0.02];
        let sharpe = calculate_sharpe(&returns, 0.0);
        assert!(sharpe > 0.0);
    }

    #[test]
    fn sortino_positive_for_positive_returns() {
        let returns = vec![0.01, -0.005, 0.02, 0.015, -0.003, 0.01];
        let sortino = calculate_sortino(&returns, 0.0);
        assert!(sortino > 0.0);
    }

    #[test]
    fn beta_of_self_is_one() {
        let returns = vec![0.01, -0.005, 0.02, 0.015, -0.01];
        let beta = calculate_beta(&returns, &returns);
        assert!((beta - 1.0).abs() < 1e-9);
    }

    #[test]
    fn correlation_of_self_is_one() {
        let returns = vec![0.01, -0.005, 0.02, 0.015, -0.01];
        let corr = calculate_correlation(&returns, &returns);
        assert!((corr - 1.0).abs() < 1e-9);
    }

    #[test]
    fn empty_inputs_return_zero() {
        assert_eq!(calculate_sharpe(&[], 0.0), 0.0);
        assert_eq!(calculate_sortino(&[], 0.0), 0.0);
        assert_eq!(calculate_max_drawdown(&[]), 0.0);
        assert_eq!(calculate_beta(&[], &[]), 0.0);
        assert_eq!(calculate_correlation(&[], &[]), 0.0);
    }
}
