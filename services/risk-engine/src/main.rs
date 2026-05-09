use quantcore_risk_engine::RiskEngine;
use quantcore_risk_engine::engine;
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

    let addr = std::env::var("RISK_ENGINE_ADDR").unwrap_or_else(|_| "0.0.0.0:50053".to_string());

    info!("Starting QuantCore Risk Engine v0.1.0");

    let engine = RiskEngine::new();
    engine::run_server(&addr, engine).await?;

    Ok(())
}
