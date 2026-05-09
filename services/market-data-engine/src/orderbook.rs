use crate::quote::RealtimeQuote;
use dashmap::DashMap;
use std::sync::Arc;

#[derive(Debug, Clone)]
pub struct PriceLevel {
    pub price: f64,
    pub quantity: i64,
    pub order_count: i32,
}

#[derive(Debug, Clone)]
pub struct OrderBook {
    pub symbol: String,
    pub bids: Vec<PriceLevel>,
    pub asks: Vec<PriceLevel>,
    pub timestamp_ns: i64,
    pub sequence: u64,
}

impl OrderBook {
    pub fn new(symbol: String, depth: usize) -> Self {
        Self {
            symbol,
            bids: Vec::with_capacity(depth),
            asks: Vec::with_capacity(depth),
            timestamp_ns: 0,
            sequence: 0,
        }
    }

    pub fn update_bid(&mut self, level: usize, price: f64, quantity: i64, order_count: i32) {
        if level < self.bids.len() {
            self.bids[level] = PriceLevel { price, quantity, order_count };
        } else {
            self.bids.push(PriceLevel { price, quantity, order_count });
        }
        self.sequence += 1;
    }

    pub fn update_ask(&mut self, level: usize, price: f64, quantity: i64, order_count: i32) {
        if level < self.asks.len() {
            self.asks[level] = PriceLevel { price, quantity, order_count };
        } else {
            self.asks.push(PriceLevel { price, quantity, order_count });
        }
        self.sequence += 1;
    }

    pub fn mid_price(&self) -> f64 {
        match (self.bids.first(), self.asks.first()) {
            (Some(b), Some(a)) => (b.price + a.price) / 2.0,
            _ => 0.0,
        }
    }

    pub fn spread(&self) -> f64 {
        match (self.bids.first(), self.asks.first()) {
            (Some(b), Some(a)) => a.price - b.price,
            _ => 0.0,
        }
    }

    pub fn is_valid(&self) -> bool {
        if self.bids.is_empty() || self.asks.is_empty() {
            return false;
        }
        if let (Some(best_bid), Some(best_ask)) = (self.bids.first(), self.asks.first()) {
            return best_bid.price < best_ask.price;
        }
        false
    }
}

pub struct OrderBookManager {
    books: Arc<DashMap<String, OrderBook>>,
    default_depth: usize,
}

impl OrderBookManager {
    pub fn new(default_depth: usize) -> Self {
        Self {
            books: Arc::new(DashMap::new()),
            default_depth,
        }
    }

    pub fn get_or_create(&self, symbol: &str) -> dashmap::mapref::entry::Ref<'_, String, OrderBook> {
        self.books.entry(symbol.to_string()).or_insert_with(|| {
            OrderBook::new(symbol.to_string(), self.default_depth)
        }).downgrade()
    }

    pub fn get(&self, symbol: &str) -> Option<dashmap::mapref::one::Ref<String, OrderBook>> {
        self.books.get(symbol)
    }

    pub fn apply_snapshot(&self, symbol: &str, book: OrderBook) {
        self.books.insert(symbol.to_string(), book);
    }
}
