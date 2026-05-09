use crate::order::Order;
use dashmap::DashMap;
use tracing::warn;

pub const MAX_STORE_SIZE: usize = 100_000;

pub struct IdempotencyStore {
    store: DashMap<String, Order>,
}

impl IdempotencyStore {
    pub fn new() -> Self {
        Self {
            store: DashMap::with_capacity(MAX_STORE_SIZE),
        }
    }

    pub fn check_and_store(&self, client_order_id: &str, order: Order) -> Option<Order> {
        use dashmap::mapref::entry::Entry;

        if self.store.len() >= MAX_STORE_SIZE {
            warn!(
                client_order_id = client_order_id,
                store_size = self.store.len(),
                "Idempotency store at capacity, cannot store new entry"
            );
            return None;
        }

        match self.store.entry(client_order_id.to_string()) {
            Entry::Occupied(e) => Some(e.get().clone()),
            Entry::Vacant(e) => {
                e.insert(order);
                None
            }
        }
    }

    pub fn contains(&self, client_order_id: &str) -> bool {
        self.store.contains_key(client_order_id)
    }

    pub fn get(&self, client_order_id: &str) -> Option<Order> {
        self.store.get(client_order_id).map(|r| r.value().clone())
    }

    pub fn remove(&self, client_order_id: &str) -> Option<Order> {
        self.store.remove(client_order_id).map(|(_, v)| v)
    }

    pub fn remove_expired(&self, ttl_ns: i64) {
        let now_ns = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0);
        let cutoff = now_ns.saturating_sub(ttl_ns);
        let before = self.store.len();
        self.store.retain(|_, order| order.created_at_ns > cutoff);
        let removed = before - self.store.len();
        if removed > 0 {
            tracing::info!(removed = removed, remaining = self.store.len(), "Expired idempotency entries cleaned up");
        }
    }

    pub fn len(&self) -> usize {
        self.store.len()
    }

    pub fn is_empty(&self) -> bool {
        self.store.is_empty()
    }
}

impl Default for IdempotencyStore {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::order::{OrderSide, OrderType};

    fn make_order(client_order_id: &str) -> Order {
        Order::new(
            uuid::Uuid::new_v4().to_string(),
            client_order_id.to_string(),
            "600000.SH".to_string(),
            OrderSide::Buy,
            OrderType::Limit,
            1000,
            10.0,
            0.0,
            "strat-1".to_string(),
            "acct-1".to_string(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0),
        )
    }

    #[test]
    fn store_new_entry() {
        let store = IdempotencyStore::new();
        let order = make_order("client-1");
        let result = store.check_and_store("client-1", order);
        assert!(result.is_none());
        assert_eq!(store.len(), 1);
    }

    #[test]
    fn duplicate_returns_existing() {
        let store = IdempotencyStore::new();
        let order1 = make_order("client-1");
        store.check_and_store("client-1", order1);
        let order2 = make_order("client-1");
        let existing = store.check_and_store("client-1", order2);
        assert!(existing.is_some());
        assert_eq!(store.len(), 1);
    }

    #[test]
    fn contains_check() {
        let store = IdempotencyStore::new();
        let order = make_order("client-1");
        store.check_and_store("client-1", order);
        assert!(store.contains("client-1"));
        assert!(!store.contains("client-2"));
    }

    #[test]
    fn remove_entry() {
        let store = IdempotencyStore::new();
        let order = make_order("client-1");
        store.check_and_store("client-1", order);
        let removed = store.remove("client-1");
        assert!(removed.is_some());
        assert!(store.is_empty());
    }

    #[test]
    fn remove_expired_removes_old_entries() {
        let store = IdempotencyStore::new();
        let order = make_order("client-1");
        store.check_and_store("client-1", order);
        let ttl_ns = 1_i64;
        store.remove_expired(ttl_ns);
        assert!(store.is_empty());
    }
}
