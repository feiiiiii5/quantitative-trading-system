use crate::orderbook::OrderBookManager;
use crate::quote::RealtimeQuote;
use dashmap::DashMap;
use std::sync::Arc;
use tokio::sync::broadcast;
use tracing::info;

#[derive(Debug, Clone)]
pub struct MarketDataSnapshot {
    pub quotes: Arc<DashMap<String, RealtimeQuote>>,
    pub orderbooks: Arc<OrderBookManager>,
    pub update_tx: broadcast::Sender<MarketDataEvent>,
}

#[derive(Debug, Clone)]
pub enum MarketDataEvent {
    QuoteUpdate(RealtimeQuote),
    DepthUpdate(String),
}

impl MarketDataSnapshot {
    pub fn new(orderbook_depth: usize) -> Self {
        let (update_tx, _) = broadcast::channel(4096);
        Self {
            quotes: Arc::new(DashMap::new()),
            orderbooks: Arc::new(OrderBookManager::new(orderbook_depth)),
            update_tx,
        }
    }

    pub fn update_quote(&self, quote: RealtimeQuote) {
        let symbol = quote.symbol.clone();
        self.quotes.insert(symbol.clone(), quote.clone());
        let _ = self.update_tx.send(MarketDataEvent::QuoteUpdate(quote));
    }

    pub fn get_quote(&self, symbol: &str) -> Option<RealtimeQuote> {
        self.quotes.get(symbol).map(|r| r.value().clone())
    }

    pub fn get_quotes(&self, symbols: &[String]) -> Vec<RealtimeQuote> {
        symbols
            .iter()
            .filter_map(|s| self.get_quote(s))
            .collect()
    }

    pub fn subscribe(&self) -> broadcast::Receiver<MarketDataEvent> {
        self.update_tx.subscribe()
    }

    pub fn snapshot_stats(&self) -> (usize, usize) {
        (self.quotes.len(), self.orderbooks.books.len())
    }
}
