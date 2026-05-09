use serde::{Deserialize, Serialize};

const COMMISSION_RATE: f64 = 0.0003;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum OrderSide {
    Buy,
    Sell,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum OrderType {
    Market,
    Limit,
    Stop,
    StopLimit,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum OrderStatus {
    Pending,
    Accepted,
    PartiallyFilled,
    Filled,
    Cancelled,
    Rejected,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FillResult {
    pub quantity: i64,
    pub price: f64,
    pub commission: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub order_id: String,
    pub client_order_id: String,
    pub symbol: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub quantity: i64,
    pub price: f64,
    pub stop_price: f64,
    pub status: OrderStatus,
    pub filled_quantity: i64,
    pub avg_fill_price: f64,
    pub commission: f64,
    pub strategy_id: String,
    pub account_id: String,
    pub created_at_ns: i64,
    pub updated_at_ns: i64,
}

impl Order {
    pub fn new(
        order_id: String,
        client_order_id: String,
        symbol: String,
        side: OrderSide,
        order_type: OrderType,
        quantity: i64,
        price: f64,
        stop_price: f64,
        strategy_id: String,
        account_id: String,
        created_at_ns: i64,
    ) -> Self {
        Self {
            order_id,
            client_order_id,
            symbol,
            side,
            order_type,
            quantity,
            price,
            stop_price,
            status: OrderStatus::Pending,
            filled_quantity: 0,
            avg_fill_price: 0.0,
            commission: 0.0,
            strategy_id,
            account_id,
            created_at_ns,
            updated_at_ns: created_at_ns,
        }
    }

    pub fn fill(&mut self, qty: i64, price: f64) -> Result<FillResult, String> {
        if !self.is_active() {
            return Err(format!("cannot fill order in status {:?}", self.status));
        }
        let new_filled = self
            .filled_quantity
            .checked_add(qty)
            .ok_or_else(|| "fill quantity overflow".to_string())?;
        if new_filled > self.quantity {
            return Err(format!(
                "fill quantity {} exceeds order quantity {}",
                new_filled, self.quantity
            ));
        }
        let total_value =
            self.avg_fill_price * self.filled_quantity as f64 + price * qty as f64;
        self.avg_fill_price = if new_filled > 0 {
            total_value / new_filled as f64
        } else {
            0.0
        };
        self.filled_quantity = new_filled;
        let commission = price * qty as f64 * COMMISSION_RATE;
        self.commission += commission;
        self.status = if self.filled_quantity == self.quantity {
            OrderStatus::Filled
        } else {
            OrderStatus::PartiallyFilled
        };
        self.updated_at_ns = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0);
        Ok(FillResult {
            quantity: qty,
            price,
            commission,
        })
    }

    pub fn cancel(&mut self) -> Result<(), String> {
        if !self.is_active() {
            return Err(format!("cannot cancel order in status {:?}", self.status));
        }
        self.status = OrderStatus::Cancelled;
        self.updated_at_ns = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0);
        Ok(())
    }

    pub fn reject(&mut self, reason: &str) -> Result<(), String> {
        if self.status != OrderStatus::Pending {
            return Err(format!("cannot reject order in status {:?}", self.status));
        }
        tracing::warn!(order_id = %self.order_id, reason = reason, "Order rejected");
        self.status = OrderStatus::Rejected;
        self.updated_at_ns = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0);
        Ok(())
    }

    pub fn is_active(&self) -> bool {
        matches!(
            self.status,
            OrderStatus::Pending | OrderStatus::Accepted | OrderStatus::PartiallyFilled
        )
    }

    pub fn is_terminal(&self) -> bool {
        matches!(
            self.status,
            OrderStatus::Filled | OrderStatus::Cancelled | OrderStatus::Rejected
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_order() -> Order {
        Order::new(
            "ord-1".to_string(),
            "client-1".to_string(),
            "600000.SH".to_string(),
            OrderSide::Buy,
            OrderType::Limit,
            1000,
            10.0,
            0.0,
            "strat-1".to_string(),
            "acct-1".to_string(),
            1_000_000_000,
        )
    }

    #[test]
    fn new_order_is_pending() {
        let order = make_order();
        assert_eq!(order.status, OrderStatus::Pending);
        assert!(order.is_active());
        assert!(!order.is_terminal());
        assert_eq!(order.filled_quantity, 0);
    }

    #[test]
    fn partial_fill() {
        let mut order = make_order();
        let result = order.fill(500, 10.5).expect("fill should succeed");
        assert_eq!(result.quantity, 500);
        assert_eq!(order.filled_quantity, 500);
        assert_eq!(order.status, OrderStatus::PartiallyFilled);
        assert!(order.is_active());
    }

    #[test]
    fn full_fill() {
        let mut order = make_order();
        let result = order.fill(1000, 10.5).expect("fill should succeed");
        assert_eq!(result.quantity, 1000);
        assert_eq!(order.filled_quantity, 1000);
        assert_eq!(order.status, OrderStatus::Filled);
        assert!(order.is_terminal());
    }

    #[test]
    fn fill_exceeds_quantity() {
        let mut order = make_order();
        let err = order.fill(1001, 10.5).expect_err("should fail");
        assert!(err.contains("exceeds"));
    }

    #[test]
    fn cancel_active_order() {
        let mut order = make_order();
        order.status = OrderStatus::Accepted;
        order.cancel().expect("cancel should succeed");
        assert_eq!(order.status, OrderStatus::Cancelled);
        assert!(order.is_terminal());
    }

    #[test]
    fn cancel_filled_order_fails() {
        let mut order = make_order();
        order.status = OrderStatus::Filled;
        let err = order.cancel().expect_err("should fail");
        assert!(err.contains("cannot cancel"));
    }

    #[test]
    fn reject_pending_order() {
        let mut order = make_order();
        order.reject("invalid symbol").expect("reject should succeed");
        assert_eq!(order.status, OrderStatus::Rejected);
        assert!(order.is_terminal());
    }

    #[test]
    fn reject_accepted_order_fails() {
        let mut order = make_order();
        order.status = OrderStatus::Accepted;
        let err = order.reject("reason").expect_err("should fail");
        assert!(err.contains("cannot reject"));
    }

    #[test]
    fn weighted_avg_fill_price() {
        let mut order = make_order();
        order.fill(500, 10.0).expect("fill 1");
        order.fill(500, 12.0).expect("fill 2");
        let expected_avg = (10.0 * 500.0 + 12.0 * 500.0) / 1000.0;
        assert!((order.avg_fill_price - expected_avg).abs() < f64::EPSILON);
    }
}
