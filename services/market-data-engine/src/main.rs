mod lib;
mod orderbook;
mod quote;
mod server;
mod snapshot;

use snapshot::MarketDataSnapshot;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .json()
        .init();

    let addr = std::env::var("MARKET_DATA_ADDR").unwrap_or_else(|_| "0.0.0.0:50051".to_string());
    let orderbook_depth = std::env::var("ORDERBOOK_DEPTH")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(10);

    info!(
        "Starting QuantCore Market Data Engine v0.1.0 (depth={})",
        orderbook_depth
    );

    let snapshot = MarketDataSnapshot::new(orderbook_depth);
    let (qs, obs) = snapshot.snapshot_stats();
    info!("Snapshot initialized: {} quotes, {} orderbooks", qs, obs);

    server::run_server(&addr, snapshot).await?;

    Ok(())
}
