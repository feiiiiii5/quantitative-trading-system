use crate::order::Order;
use serde::{Deserialize, Serialize};
use std::fmt;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Route {
    pub exchange_id: String,
    pub latency_ms: u64,
    pub fill_rate: f64,
    pub max_quantity: i64,
}

impl fmt::Display for Route {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Route({}: latency={}ms, fill_rate={:.2}%, max_qty={})",
            self.exchange_id, self.latency_ms, self.fill_rate * 100.0, self.max_quantity
        )
    }
}

fn route_score(route: &Route) -> f64 {
    route.fill_rate / (1.0 + route.latency_ms as f64 / 100.0)
}

pub struct SmartOrderRouter {
    routes: parking_lot::RwLock<Vec<Route>>,
}

impl SmartOrderRouter {
    pub fn new() -> Self {
        let default_routes = vec![
            Route {
                exchange_id: "SSE".to_string(),
                latency_ms: 2,
                fill_rate: 0.95,
                max_quantity: 1_000_000,
            },
            Route {
                exchange_id: "SZSE".to_string(),
                latency_ms: 3,
                fill_rate: 0.93,
                max_quantity: 500_000,
            },
        ];
        Self {
            routes: parking_lot::RwLock::new(default_routes),
        }
    }

    pub fn route(&self, order: &Order) -> Option<Route> {
        let routes = self.routes.read();
        let mut candidates: Vec<&Route> = routes
            .iter()
            .filter(|r| r.max_quantity >= order.quantity)
            .collect();

        candidates.sort_by(|a, b| route_score(b).total_cmp(&route_score(a)));

        candidates.into_iter().next().cloned()
    }

    pub fn add_route(&self, route: Route) {
        let mut routes = self.routes.write();
        tracing::info!(exchange_id = %route.exchange_id, "Route added");
        routes.push(route);
    }

    pub fn remove_route(&self, exchange_id: &str) -> bool {
        let mut routes = self.routes.write();
        let before = routes.len();
        routes.retain(|r| r.exchange_id != exchange_id);
        let removed = routes.len() != before;
        if removed {
            tracing::info!(exchange_id = exchange_id, "Route removed");
        }
        removed
    }

    pub fn routes(&self) -> Vec<Route> {
        self.routes.read().clone()
    }
}

impl Default for SmartOrderRouter {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::order::{OrderSide, OrderType};

    fn make_order(symbol: &str, quantity: i64, order_type: OrderType) -> Order {
        Order::new(
            uuid::Uuid::new_v4().to_string(),
            "client-1".to_string(),
            symbol.to_string(),
            OrderSide::Buy,
            order_type,
            quantity,
            10.0,
            0.0,
            "strat-1".to_string(),
            "acct-1".to_string(),
            1_000_000_000,
        )
    }

    #[test]
    fn default_routes_exist() {
        let router = SmartOrderRouter::new();
        let routes = router.routes();
        assert_eq!(routes.len(), 2);
        assert!(routes.iter().any(|r| r.exchange_id == "SSE"));
        assert!(routes.iter().any(|r| r.exchange_id == "SZSE"));
    }

    #[test]
    fn route_selects_best() {
        let router = SmartOrderRouter::new();
        let order = make_order("600000.SH", 100, OrderType::Limit);
        let route = router.route(&order);
        assert!(route.is_some());
        assert_eq!(route.unwrap().exchange_id, "SSE");
    }

    #[test]
    fn route_no_capacity() {
        let router = SmartOrderRouter::new();
        let order = make_order("600000.SH", 2_000_000, OrderType::Limit);
        let route = router.route(&order);
        assert!(route.is_none());
    }

    #[test]
    fn add_and_remove_route() {
        let router = SmartOrderRouter::new();
        router.add_route(Route {
            exchange_id: "HKEX".to_string(),
            latency_ms: 10,
            fill_rate: 0.90,
            max_quantity: 100_000,
        });
        assert_eq!(router.routes().len(), 3);
        assert!(router.remove_route("HKEX"));
        assert_eq!(router.routes().len(), 2);
        assert!(!router.remove_route("NONEXISTENT"));
    }
}
