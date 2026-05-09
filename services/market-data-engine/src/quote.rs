use serde::{Deserialize, Serialize};
use std::time::Instant;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RealtimeQuote {
    pub symbol: String,
    pub price: f64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub prev_close: f64,
    pub volume: i64,
    pub amount: f64,
    pub bid_price: f64,
    pub ask_price: f64,
    pub bid_volume: i64,
    pub ask_volume: i64,
    pub change_pct: f64,
    pub turnover_rate: f64,
    pub timestamp_ns: i64,
}

impl RealtimeQuote {
    pub fn validate(&self) -> bool {
        if self.symbol.is_empty() {
            return false;
        }
        if self.price <= 0.0 || self.close <= 0.0 {
            return false;
        }
        if self.high < self.low {
            return false;
        }
        if self.volume < 0 || self.amount < 0.0 {
            return false;
        }
        true
    }

    pub fn update_price(&mut self, new_price: f64) {
        self.price = new_price;
        if new_price > self.high {
            self.high = new_price;
        }
        if new_price < self.low || self.low <= 0.0 {
            self.low = new_price;
        }
        self.close = new_price;
        if self.prev_close > 0.0 {
            self.change_pct = (new_price - self.prev_close) / self.prev_close * 100.0;
        }
    }
}

#[derive(Debug, Clone)]
pub struct Tick {
    pub symbol: String,
    pub price: f64,
    pub volume: i64,
    pub side: TickSide,
    pub timestamp_ns: i64,
    pub received_at: Instant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TickSide {
    Buy,
    Sell,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MarketPhase {
    PreOpen,
    Open,
    LunchBreak,
    Afternoon,
    Close,
    AfterHours,
}
