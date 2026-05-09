use crate::idempotency::IdempotencyStore;
use crate::order::{Order, OrderSide, OrderStatus, OrderType};
use crate::router::SmartOrderRouter;
use dashmap::DashMap;
use tokio::sync::broadcast;

const BROADCAST_CAPACITY: usize = 1024;
const IDEMPOTENCY_TTL_NS: i64 = 86_400_000_000_000;

fn now_ns() -> i64 {
    chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0)
}

#[derive(Debug, Clone)]
pub enum OrderEvent {
    Submitted {
        order_id: String,
        status: OrderStatus,
        account_id: String,
        symbol: String,
        timestamp_ns: i64,
    },
    Filled {
        order_id: String,
        status: OrderStatus,
        filled_quantity: i64,
        fill_price: f64,
        commission: f64,
        account_id: String,
        symbol: String,
        timestamp_ns: i64,
    },
    Cancelled {
        order_id: String,
        status: OrderStatus,
        account_id: String,
        symbol: String,
        timestamp_ns: i64,
    },
    Rejected {
        order_id: String,
        status: OrderStatus,
        reason: String,
        account_id: String,
        symbol: String,
        timestamp_ns: i64,
    },
}

impl OrderEvent {
    pub fn order_id(&self) -> &str {
        match self {
            OrderEvent::Submitted { order_id, .. }
            | OrderEvent::Filled { order_id, .. }
            | OrderEvent::Cancelled { order_id, .. }
            | OrderEvent::Rejected { order_id, .. } => order_id,
        }
    }

    pub fn event_type(&self) -> &'static str {
        match self {
            OrderEvent::Submitted { .. } => "submitted",
            OrderEvent::Filled { .. } => "filled",
            OrderEvent::Cancelled { .. } => "cancelled",
            OrderEvent::Rejected { .. } => "rejected",
        }
    }

    pub fn account_id(&self) -> &str {
        match self {
            OrderEvent::Submitted { account_id, .. }
            | OrderEvent::Filled { account_id, .. }
            | OrderEvent::Cancelled { account_id, .. }
            | OrderEvent::Rejected { account_id, .. } => account_id,
        }
    }

    pub fn symbol(&self) -> &str {
        match self {
            OrderEvent::Submitted { symbol, .. }
            | OrderEvent::Filled { symbol, .. }
            | OrderEvent::Cancelled { symbol, .. }
            | OrderEvent::Rejected { symbol, .. } => symbol,
        }
    }
}

#[derive(Debug, Clone)]
pub struct NewOrder {
    pub client_order_id: String,
    pub symbol: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub quantity: i64,
    pub price: f64,
    pub stop_price: f64,
    pub strategy_id: String,
    pub account_id: String,
}

#[derive(Debug, Clone)]
pub struct SubmitResult {
    pub order_id: String,
    pub client_order_id: String,
    pub status: OrderStatus,
    pub reject_reason: String,
    pub timestamp_ns: i64,
}

#[derive(Debug, Clone)]
pub struct CancelResult {
    pub success: bool,
    pub order_id: String,
    pub message: String,
}

#[derive(Debug, Clone)]
pub struct OrderStatusResult {
    pub order_id: String,
    pub client_order_id: String,
    pub symbol: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub status: OrderStatus,
    pub quantity: i64,
    pub filled_quantity: i64,
    pub avg_fill_price: f64,
    pub commission: f64,
    pub timestamp_ns: i64,
}

impl From<&Order> for OrderStatusResult {
    fn from(order: &Order) -> Self {
        Self {
            order_id: order.order_id.clone(),
            client_order_id: order.client_order_id.clone(),
            symbol: order.symbol.clone(),
            side: order.side,
            order_type: order.order_type,
            status: order.status,
            quantity: order.quantity,
            filled_quantity: order.filled_quantity,
            avg_fill_price: order.avg_fill_price,
            commission: order.commission,
            timestamp_ns: order.updated_at_ns,
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("validation failed: {0}")]
    Validation(String),
    #[error("order not found: {0}")]
    NotFound(String),
    #[error("cannot cancel: {0}")]
    CannotCancel(String),
    #[error("idempotency store at capacity")]
    StoreAtCapacity,
}

pub struct OrderEngine {
    orders: DashMap<String, Order>,
    client_order_index: DashMap<String, String>,
    idempotency: IdempotencyStore,
    router: SmartOrderRouter,
    event_tx: broadcast::Sender<OrderEvent>,
}

impl OrderEngine {
    pub fn new() -> Self {
        let (event_tx, _) = broadcast::channel(BROADCAST_CAPACITY);
        Self {
            orders: DashMap::new(),
            client_order_index: DashMap::new(),
            idempotency: IdempotencyStore::new(),
            router: SmartOrderRouter::new(),
            event_tx,
        }
    }

    pub fn with_router(router: SmartOrderRouter) -> Self {
        let (event_tx, _) = broadcast::channel(BROADCAST_CAPACITY);
        Self {
            orders: DashMap::new(),
            client_order_index: DashMap::new(),
            idempotency: IdempotencyStore::new(),
            router,
            event_tx,
        }
    }

    pub fn submit_order(&self, new_order: NewOrder) -> Result<SubmitResult, EngineError> {
        if let Err(e) = self.validate_order(&new_order) {
            let order_id = uuid::Uuid::new_v4().to_string();
            let now = now_ns();
            let reason = e.to_string();
            let mut order = Order::new(
                order_id.clone(),
                new_order.client_order_id.clone(),
                new_order.symbol.clone(),
                new_order.side,
                new_order.order_type,
                new_order.quantity,
                new_order.price,
                new_order.stop_price,
                new_order.strategy_id.clone(),
                new_order.account_id.clone(),
                now,
            );
            order.reject(&reason).ok();
            self.orders.insert(order_id.clone(), order);
            self.client_order_index
                .insert(new_order.client_order_id.clone(), order_id.clone());
            let _ = self.event_tx.send(OrderEvent::Rejected {
                order_id: order_id.clone(),
                status: OrderStatus::Rejected,
                reason,
                account_id: new_order.account_id,
                symbol: new_order.symbol,
                timestamp_ns: now,
            });
            return Ok(SubmitResult {
                order_id,
                client_order_id: new_order.client_order_id,
                status: OrderStatus::Rejected,
                reject_reason: reason,
                timestamp_ns: now,
            });
        }

        let order_id = uuid::Uuid::new_v4().to_string();
        let now = now_ns();
        let mut order = Order::new(
            order_id,
            new_order.client_order_id.clone(),
            new_order.symbol.clone(),
            new_order.side,
            new_order.order_type,
            new_order.quantity,
            new_order.price,
            new_order.stop_price,
            new_order.strategy_id.clone(),
            new_order.account_id.clone(),
            now,
        );

        if let Some(existing) = self
            .idempotency
            .check_and_store(&order.client_order_id, order.clone())
        {
            tracing::warn!(
                client_order_id = %new_order.client_order_id,
                existing_order_id = %existing.order_id,
                "Duplicate order detected, returning existing"
            );
            let current = self
                .orders
                .get(&existing.order_id)
                .map(|r| r.value().clone())
                .unwrap_or(existing);
            return Ok(SubmitResult {
                order_id: current.order_id,
                client_order_id: current.client_order_id,
                status: current.status,
                reject_reason: String::new(),
                timestamp_ns: current.updated_at_ns,
            });
        }

        let route = self.router.route(&order);
        match &route {
            Some(r) => {
                tracing::info!(
                    order_id = %order.order_id,
                    exchange = %r.exchange_id,
                    "Order routed"
                );
            }
            None => {
                tracing::warn!(
                    order_id = %order.order_id,
                    symbol = %order.symbol,
                    "No route available for symbol"
                );
            }
        }

        order.status = OrderStatus::Accepted;
        order.updated_at_ns = now_ns();

        let result_order_id = order.order_id.clone();
        let result_client_order_id = order.client_order_id.clone();
        self.orders.insert(order.order_id.clone(), order);
        self.client_order_index
            .insert(new_order.client_order_id, result_order_id.clone());

        let _ = self.event_tx.send(OrderEvent::Submitted {
            order_id: result_order_id.clone(),
            status: OrderStatus::Accepted,
            account_id: new_order.account_id,
            symbol: new_order.symbol,
            timestamp_ns: now_ns(),
        });

        Ok(SubmitResult {
            order_id: result_order_id,
            client_order_id: result_client_order_id,
            status: OrderStatus::Accepted,
            reject_reason: String::new(),
            timestamp_ns: now_ns(),
        })
    }

    pub fn cancel_order(&self, order_id: &str) -> Result<CancelResult, EngineError> {
        let (account_id, symbol) = {
            let mut order_ref = self
                .orders
                .get_mut(order_id)
                .ok_or_else(|| EngineError::NotFound(order_id.to_string()))?;

            if !order_ref.is_active() {
                return Err(EngineError::CannotCancel(format!(
                    "{:?}",
                    order_ref.status
                )));
            }

            order_ref
                .cancel()
                .map_err(EngineError::CannotCancel)?;

            (order_ref.account_id.clone(), order_ref.symbol.clone())
        };

        let _ = self.event_tx.send(OrderEvent::Cancelled {
            order_id: order_id.to_string(),
            status: OrderStatus::Cancelled,
            account_id,
            symbol,
            timestamp_ns: now_ns(),
        });

        Ok(CancelResult {
            success: true,
            order_id: order_id.to_string(),
            message: "Order cancelled successfully".to_string(),
        })
    }

    pub fn cancel_order_by_client_id(
        &self,
        client_order_id: &str,
    ) -> Result<CancelResult, EngineError> {
        let order_id = self
            .client_order_index
            .get(client_order_id)
            .map(|r| r.value().clone())
            .ok_or_else(|| EngineError::NotFound(client_order_id.to_string()))?;
        self.cancel_order(&order_id)
    }

    pub fn get_order_status(
        &self,
        order_id: Option<&str>,
        client_order_id: Option<&str>,
    ) -> Option<OrderStatusResult> {
        let order = match (order_id, client_order_id) {
            (Some(id), _) => self.orders.get(id).map(|r| r.value().clone()),
            (None, Some(cid)) => self
                .client_order_index
                .get(cid)
                .and_then(|id| self.orders.get(id.value()).map(|r| r.value().clone())),
            (None, None) => None,
        };
        order.as_ref().map(OrderStatusResult::from)
    }

    pub fn stream_order_updates(&self) -> broadcast::Receiver<OrderEvent> {
        self.event_tx.subscribe()
    }

    fn validate_order(&self, order: &NewOrder) -> Result<(), EngineError> {
        if order.quantity <= 0 {
            return Err(EngineError::Validation(
                "quantity must be positive".to_string(),
            ));
        }
        if matches!(
            order.order_type,
            OrderType::Limit | OrderType::StopLimit
        ) && order.price <= 0.0
        {
            return Err(EngineError::Validation(
                "price must be positive for limit orders".to_string(),
            ));
        }
        if matches!(order.order_type, OrderType::Stop | OrderType::StopLimit)
            && order.stop_price <= 0.0
        {
            return Err(EngineError::Validation(
                "stop_price must be positive for stop orders".to_string(),
            ));
        }
        if order.symbol.is_empty() {
            return Err(EngineError::Validation(
                "symbol must not be empty".to_string(),
            ));
        }
        Ok(())
    }

    pub fn cleanup_expired_idempotency(&self) {
        self.idempotency.remove_expired(IDEMPOTENCY_TTL_NS);
    }

    pub fn order_count(&self) -> usize {
        self.orders.len()
    }
}

impl Default for OrderEngine {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_new_order(client_order_id: &str) -> NewOrder {
        NewOrder {
            client_order_id: client_order_id.to_string(),
            symbol: "600000.SH".to_string(),
            side: OrderSide::Buy,
            order_type: OrderType::Limit,
            quantity: 1000,
            price: 10.0,
            stop_price: 0.0,
            strategy_id: "strat-1".to_string(),
            account_id: "acct-1".to_string(),
        }
    }

    #[test]
    fn submit_valid_order() {
        let engine = OrderEngine::new();
        let result = engine
            .submit_order(make_new_order("client-1"))
            .expect("submit should succeed");
        assert_eq!(result.status, OrderStatus::Accepted);
        assert!(result.order_id.len() > 0);
        assert_eq!(result.client_order_id, "client-1");
    }

    #[test]
    fn submit_duplicate_order_returns_existing() {
        let engine = OrderEngine::new();
        let first = engine
            .submit_order(make_new_order("client-1"))
            .expect("first submit");
        let second = engine
            .submit_order(make_new_order("client-1"))
            .expect("second submit");
        assert_eq!(first.order_id, second.order_id);
        assert_eq!(engine.order_count(), 1);
    }

    #[test]
    fn submit_invalid_quantity() {
        let engine = OrderEngine::new();
        let mut order = make_new_order("client-bad");
        order.quantity = 0;
        let result = engine.submit_order(order).expect("should return result");
        assert_eq!(result.status, OrderStatus::Rejected);
        assert!(result.reject_reason.contains("quantity"));
    }

    #[test]
    fn submit_limit_order_without_price() {
        let engine = OrderEngine::new();
        let mut order = make_new_order("client-noprice");
        order.price = 0.0;
        order.order_type = OrderType::Limit;
        let result = engine.submit_order(order).expect("should return result");
        assert_eq!(result.status, OrderStatus::Rejected);
        assert!(result.reject_reason.contains("price"));
    }

    #[test]
    fn submit_empty_symbol() {
        let engine = OrderEngine::new();
        let mut order = make_new_order("client-nosym");
        order.symbol = String::new();
        let result = engine.submit_order(order).expect("should return result");
        assert_eq!(result.status, OrderStatus::Rejected);
        assert!(result.reject_reason.contains("symbol"));
    }

    #[test]
    fn cancel_accepted_order() {
        let engine = OrderEngine::new();
        let submit_result = engine
            .submit_order(make_new_order("client-cancel"))
            .expect("submit");
        let cancel_result = engine
            .cancel_order(&submit_result.order_id)
            .expect("cancel");
        assert!(cancel_result.success);
        let status = engine
            .get_order_status(Some(&submit_result.order_id), None)
            .expect("should find order");
        assert_eq!(status.status, OrderStatus::Cancelled);
    }

    #[test]
    fn cancel_nonexistent_order() {
        let engine = OrderEngine::new();
        let result = engine.cancel_order("nonexistent");
        assert!(result.is_err());
    }

    #[test]
    fn cancel_by_client_order_id() {
        let engine = OrderEngine::new();
        engine
            .submit_order(make_new_order("client-cancel-cid"))
            .expect("submit");
        let result = engine
            .cancel_order_by_client_id("client-cancel-cid")
            .expect("cancel");
        assert!(result.success);
    }

    #[test]
    fn get_order_status_by_order_id() {
        let engine = OrderEngine::new();
        let submit_result = engine
            .submit_order(make_new_order("client-status"))
            .expect("submit");
        let status = engine
            .get_order_status(Some(&submit_result.order_id), None)
            .expect("should find");
        assert_eq!(status.order_id, submit_result.order_id);
        assert_eq!(status.symbol, "600000.SH");
    }

    #[test]
    fn get_order_status_by_client_order_id() {
        let engine = OrderEngine::new();
        engine
            .submit_order(make_new_order("client-status-cid"))
            .expect("submit");
        let status = engine
            .get_order_status(None, Some("client-status-cid"))
            .expect("should find");
        assert_eq!(status.client_order_id, "client-status-cid");
    }

    #[test]
    fn stream_order_updates() {
        let engine = OrderEngine::new();
        let mut rx = engine.stream_order_updates();
        engine
            .submit_order(make_new_order("client-stream"))
            .expect("submit");
        let event = rx.try_recv().expect("should receive event");
        assert_eq!(event.event_type(), "submitted");
    }
}
