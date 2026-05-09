use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskLimits {
    pub max_position_pct: f64,
    pub max_drawdown_pct: f64,
    pub max_daily_loss_pct: f64,
    pub max_concentration_pct: f64,
    pub max_leverage: f64,
    pub max_open_trades: u32,
}

impl Default for RiskLimits {
    fn default() -> Self {
        Self {
            max_position_pct: 0.30,
            max_drawdown_pct: 0.15,
            max_daily_loss_pct: 0.05,
            max_concentration_pct: 0.30,
            max_leverage: 1.0,
            max_open_trades: 10,
        }
    }
}

impl RiskLimits {
    pub fn validate(&self) -> Result<(), String> {
        if self.max_position_pct <= 0.0 || self.max_position_pct > 1.0 {
            return Err(format!(
                "max_position_pct must be in (0, 1], got {}",
                self.max_position_pct
            ));
        }
        if self.max_drawdown_pct <= 0.0 || self.max_drawdown_pct > 1.0 {
            return Err(format!(
                "max_drawdown_pct must be in (0, 1], got {}",
                self.max_drawdown_pct
            ));
        }
        if self.max_daily_loss_pct <= 0.0 || self.max_daily_loss_pct > 1.0 {
            return Err(format!(
                "max_daily_loss_pct must be in (0, 1], got {}",
                self.max_daily_loss_pct
            ));
        }
        if self.max_concentration_pct <= 0.0 || self.max_concentration_pct > 1.0 {
            return Err(format!(
                "max_concentration_pct must be in (0, 1], got {}",
                self.max_concentration_pct
            ));
        }
        if self.max_leverage <= 0.0 {
            return Err(format!(
                "max_leverage must be positive, got {}",
                self.max_leverage
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct AccountLimits {
    limits: Arc<DashMap<String, RiskLimits>>,
}

impl AccountLimits {
    pub fn new() -> Self {
        Self {
            limits: Arc::new(DashMap::new()),
        }
    }

    pub fn set_limits(&self, account_id: &str, limits: RiskLimits) -> Result<(), String> {
        limits.validate()?;
        self.limits.insert(account_id.to_string(), limits);
        Ok(())
    }

    pub fn get_limits(&self, account_id: &str) -> RiskLimits {
        self.limits
            .get(account_id)
            .map(|r| r.value().clone())
            .unwrap_or_default()
    }

    pub fn reset_to_default(&self, account_id: &str) {
        self.limits.insert(account_id.to_string(), RiskLimits::default());
    }

    pub fn remove(&self, account_id: &str) {
        self.limits.remove(account_id);
    }
}

impl Default for AccountLimits {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_limits_are_valid() {
        assert!(RiskLimits::default().validate().is_ok());
    }

    #[test]
    fn invalid_position_pct_rejected() {
        let mut limits = RiskLimits::default();
        limits.max_position_pct = 0.0;
        assert!(limits.validate().is_err());
        limits.max_position_pct = 1.5;
        assert!(limits.validate().is_err());
    }

    #[test]
    fn account_limits_fallback_to_default() {
        let al = AccountLimits::new();
        let limits = al.get_limits("nonexistent");
        assert_eq!(limits.max_position_pct, 0.30);
    }

    #[test]
    fn set_and_get_limits() {
        let al = AccountLimits::new();
        let mut custom = RiskLimits::default();
        custom.max_leverage = 2.0;
        al.set_limits("acc1", custom.clone()).unwrap();
        let retrieved = al.get_limits("acc1");
        assert_eq!(retrieved.max_leverage, 2.0);
    }

    #[test]
    fn reset_to_default() {
        let al = AccountLimits::new();
        let mut custom = RiskLimits::default();
        custom.max_leverage = 5.0;
        al.set_limits("acc1", custom).unwrap();
        al.reset_to_default("acc1");
        assert_eq!(al.get_limits("acc1").max_leverage, 1.0);
    }
}
