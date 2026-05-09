use crate::limits::{AccountLimits, RiskLimits};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreTradeCheck {
    pub account_id: String,
    pub symbol: String,
    pub side: i32,
    pub quantity: i64,
    pub price: f64,
    pub strategy_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Position {
    pub symbol: String,
    pub quantity: i64,
    pub market_value: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccountState {
    pub equity: f64,
    pub peak_value: f64,
    pub pnl_today: f64,
    pub open_positions: Vec<Position>,
    pub gross_exposure: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreTradeResult {
    pub approved: bool,
    pub rejection_reasons: Vec<String>,
    pub current_exposure: f64,
    pub max_exposure: f64,
    pub current_drawdown: f64,
    pub max_drawdown: f64,
    pub concentration_pct: f64,
    pub max_concentration_pct: f64,
}

pub struct PreTradeChecker {
    limits: AccountLimits,
}

impl PreTradeChecker {
    pub fn new(limits: AccountLimits) -> Self {
        Self { limits }
    }

    pub fn check_concentration(
        &self,
        positions: &[Position],
        new_order: &PreTradeCheck,
        limits: &RiskLimits,
    ) -> Result<f64, String> {
        let total_value: f64 = positions.iter().map(|p| p.market_value).sum();
        let new_value = new_order.quantity as f64 * new_order.price;
        let combined_total = total_value + new_value;

        if combined_total <= 0.0 {
            return Ok(0.0);
        }

        let mut symbol_values: HashMap<String, f64> = HashMap::new();
        for pos in positions {
            *symbol_values.entry(pos.symbol.clone()).or_insert(0.0) += pos.market_value;
        }
        *symbol_values.entry(new_order.symbol.clone()).or_insert(0.0) += new_value;

        let max_concentration = symbol_values
            .values()
            .copied()
            .fold(0.0_f64, f64::max);

        let concentration_pct = max_concentration / combined_total;

        if concentration_pct > limits.max_concentration_pct {
            return Err(format!(
                "Concentration {:.2}% exceeds limit {:.2}% (symbol concentration: {:.2}%)",
                concentration_pct * 100.0,
                limits.max_concentration_pct * 100.0,
                concentration_pct * 100.0
            ));
        }

        Ok(concentration_pct)
    }

    pub fn check_drawdown(
        &self,
        current_value: f64,
        peak_value: f64,
        limits: &RiskLimits,
    ) -> Result<f64, String> {
        if peak_value <= 0.0 {
            return Ok(0.0);
        }

        let drawdown = (peak_value - current_value) / peak_value;

        if drawdown > limits.max_drawdown_pct {
            return Err(format!(
                "Drawdown {:.2}% exceeds limit {:.2}%",
                drawdown * 100.0,
                limits.max_drawdown_pct * 100.0
            ));
        }

        Ok(drawdown)
    }

    pub fn check_daily_loss(&self, pnl_today: f64, equity: f64, limits: &RiskLimits) -> Result<(), String> {
        if equity <= 0.0 {
            return Err("Equity must be positive for daily loss check".to_string());
        }

        let daily_loss_pct = (-pnl_today) / equity;

        if pnl_today < 0.0 && daily_loss_pct > limits.max_daily_loss_pct {
            return Err(format!(
                "Daily loss {:.2}% exceeds limit {:.2}%",
                daily_loss_pct * 100.0,
                limits.max_daily_loss_pct * 100.0
            ));
        }

        Ok(())
    }

    pub fn check_open_trades(&self, count: u32, limits: &RiskLimits) -> Result<(), String> {
        if count >= limits.max_open_trades {
            return Err(format!(
                "Open trades {} at limit {}",
                count, limits.max_open_trades
            ));
        }

        Ok(())
    }

    pub fn check_leverage(
        &self,
        gross_exposure: f64,
        equity: f64,
        limits: &RiskLimits,
    ) -> Result<f64, String> {
        if equity <= 0.0 {
            return Err("Equity must be positive for leverage check".to_string());
        }

        let leverage = gross_exposure / equity;

        if leverage > limits.max_leverage {
            return Err(format!(
                "Leverage {:.2}x exceeds limit {:.2}x",
                leverage, limits.max_leverage
            ));
        }

        Ok(leverage)
    }

    pub fn run_full_check(&self, state: &AccountState, new_order: &PreTradeCheck) -> PreTradeResult {
        let limits = self.limits.get_limits(&new_order.account_id);
        let mut rejection_reasons = Vec::new();

        let new_trade_value = new_order.quantity as f64 * new_order.price;
        let projected_gross_exposure = state.gross_exposure + new_trade_value;

        let concentration_pct = match self.check_concentration(&state.open_positions, new_order, &limits) {
            Ok(pct) => pct,
            Err(reason) => {
                rejection_reasons.push(reason);
                0.0
            }
        };

        let current_drawdown = match self.check_drawdown(state.equity, state.peak_value, &limits) {
            Ok(dd) => dd,
            Err(reason) => {
                rejection_reasons.push(reason);
                0.0
            }
        };

        if let Err(reason) = self.check_daily_loss(state.pnl_today, state.equity, &limits) {
            rejection_reasons.push(reason);
        }

        if let Err(reason) = self.check_open_trades(state.open_positions.len() as u32, &limits) {
            rejection_reasons.push(reason);
        }

        if let Err(reason) = self.check_leverage(projected_gross_exposure, state.equity, &limits) {
            rejection_reasons.push(reason);
        }

        let max_exposure = state.equity * limits.max_position_pct;

        PreTradeResult {
            approved: rejection_reasons.is_empty(),
            rejection_reasons,
            current_exposure: projected_gross_exposure,
            max_exposure,
            current_drawdown,
            max_drawdown: limits.max_drawdown_pct,
            concentration_pct,
            max_concentration_pct: limits.max_concentration_pct,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn default_checker() -> PreTradeChecker {
        PreTradeChecker::new(AccountLimits::new())
    }

    fn sample_state() -> AccountState {
        AccountState {
            equity: 1_000_000.0,
            peak_value: 1_050_000.0,
            pnl_today: -2_000.0,
            open_positions: vec![
                Position {
                    symbol: "AAPL".to_string(),
                    quantity: 100,
                    market_value: 50_000.0,
                },
                Position {
                    symbol: "GOOG".to_string(),
                    quantity: 50,
                    market_value: 50_000.0,
                },
                Position {
                    symbol: "MSFT".to_string(),
                    quantity: 60,
                    market_value: 50_000.0,
                },
                Position {
                    symbol: "AMZN".to_string(),
                    quantity: 40,
                    market_value: 50_000.0,
                },
                Position {
                    symbol: "NVDA".to_string(),
                    quantity: 30,
                    market_value: 50_000.0,
                },
            ],
            gross_exposure: 250_000.0,
        }
    }

    fn sample_order() -> PreTradeCheck {
        PreTradeCheck {
            account_id: "test".to_string(),
            symbol: "TSLA".to_string(),
            side: 1,
            quantity: 10,
            price: 200.0,
            strategy_id: "strat1".to_string(),
        }
    }

    #[test]
    fn full_check_approves_valid_trade() {
        let checker = default_checker();
        let result = checker.run_full_check(&sample_state(), &sample_order());
        assert!(result.approved);
        assert!(result.rejection_reasons.is_empty());
    }

    #[test]
    fn drawdown_check_passes_within_limit() {
        let checker = default_checker();
        let limits = RiskLimits::default();
        let result = checker.check_drawdown(900_000.0, 1_000_000.0, &limits);
        assert!(result.is_ok());
        assert!((result.unwrap() - 0.10).abs() < 1e-9);
    }

    #[test]
    fn drawdown_check_fails_exceeds_limit() {
        let checker = default_checker();
        let limits = RiskLimits::default();
        let result = checker.check_drawdown(800_000.0, 1_000_000.0, &limits);
        assert!(result.is_err());
    }

    #[test]
    fn daily_loss_check_fails() {
        let checker = default_checker();
        let limits = RiskLimits::default();
        let result = checker.check_daily_loss(-60_000.0, 1_000_000.0, &limits);
        assert!(result.is_err());
    }

    #[test]
    fn open_trades_check_fails_at_limit() {
        let checker = default_checker();
        let limits = RiskLimits::default();
        let result = checker.check_open_trades(10, &limits);
        assert!(result.is_err());
    }

    #[test]
    fn leverage_check_fails() {
        let checker = default_checker();
        let limits = RiskLimits::default();
        let result = checker.check_leverage(1_500_000.0, 1_000_000.0, &limits);
        assert!(result.is_err());
    }

    #[test]
    fn concentration_check_fails() {
        let checker = default_checker();
        let limits = RiskLimits::default();
        let positions = vec![Position {
            symbol: "AAPL".to_string(),
            quantity: 1000,
            market_value: 300_000.0,
        }];
        let order = PreTradeCheck {
            account_id: "test".to_string(),
            symbol: "AAPL".to_string(),
            side: 1,
            quantity: 5000,
            price: 300.0,
            strategy_id: "s1".to_string(),
        };
        let result = checker.check_concentration(&positions, &order, &limits);
        assert!(result.is_err());
    }
}
