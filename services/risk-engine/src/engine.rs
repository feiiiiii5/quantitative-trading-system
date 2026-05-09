use crate::check::{AccountState, PreTradeCheck, PreTradeChecker, PreTradeResult};
use crate::limits::{AccountLimits, RiskLimits};
use crate::metrics::{self, RiskMetrics};
use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::broadcast;
use tonic::{Request, Response, Status};
use tracing::{error, info, warn};
use uuid::Uuid;

pub mod proto {
    tonic::include_proto!("quantcore.risk.v1");
}

use proto::risk_service_server::RiskService;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskAlert {
    pub alert_id: String,
    pub alert_type: String,
    pub severity: String,
    pub message: String,
    pub current_value: f64,
    pub threshold: f64,
    pub timestamp_ns: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Severity {
    Low,
    Medium,
    High,
    Critical,
}

impl Severity {
    pub fn as_str(&self) -> &'static str {
        match self {
            Severity::Low => "Low",
            Severity::Medium => "Medium",
            Severity::High => "High",
            Severity::Critical => "Critical",
        }
    }
}

impl std::fmt::Display for Severity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

pub struct RiskEngine {
    limits: AccountLimits,
    metrics_cache: Arc<DashMap<String, RiskMetrics>>,
    alert_tx: broadcast::Sender<RiskAlert>,
    checker: PreTradeChecker,
}

impl RiskEngine {
    pub fn new() -> Self {
        let limits = AccountLimits::new();
        let checker = PreTradeChecker::new(limits.clone());
        let (alert_tx, _) = broadcast::channel(1024);

        Self {
            limits,
            metrics_cache: Arc::new(DashMap::new()),
            alert_tx,
            checker,
        }
    }

    pub fn pre_trade_check(&self, state: &AccountState, order: &PreTradeCheck) -> PreTradeResult {
        self.checker.run_full_check(state, order)
    }

    pub fn get_risk_metrics(&self, account_id: &str) -> Option<RiskMetrics> {
        self.metrics_cache.get(account_id).map(|r| r.value().clone())
    }

    pub fn compute_and_cache_metrics(
        &self,
        account_id: &str,
        returns: &[f64],
        benchmark_returns: &[f64],
        equity_curve: &[f64],
        gross_exposure: f64,
        net_exposure: f64,
        equity: f64,
    ) -> RiskMetrics {
        let risk_free_daily = 0.0;
        let leverage = if equity > 0.0 { gross_exposure / equity } else { 0.0 };

        let metrics = RiskMetrics {
            var_95: metrics::calculate_var(returns, 0.95),
            var_99: metrics::calculate_var(returns, 0.99),
            cvar_95: metrics::calculate_cvar(returns, 0.95),
            max_drawdown: metrics::calculate_max_drawdown(equity_curve),
            sharpe_ratio: metrics::calculate_sharpe(returns, risk_free_daily),
            sortino_ratio: metrics::calculate_sortino(returns, risk_free_daily),
            beta: metrics::calculate_beta(returns, benchmark_returns),
            correlation: metrics::calculate_correlation(returns, benchmark_returns),
            leverage,
            gross_exposure,
            net_exposure,
        };

        self.metrics_cache.insert(account_id.to_string(), metrics.clone());
        metrics
    }

    pub fn stream_risk_alerts(&self) -> broadcast::Receiver<RiskAlert> {
        self.alert_tx.subscribe()
    }

    pub fn set_risk_limits(&self, account_id: &str, limits: RiskLimits) -> Result<(), String> {
        self.limits.set_limits(account_id, limits)
    }

    pub fn monitor_drawdown(&self, account_id: &str, current_value: f64, peak_value: f64) {
        let limits = self.limits.get_limits(account_id);

        if peak_value <= 0.0 {
            return;
        }

        let drawdown = (peak_value - current_value) / peak_value;
        let warning_threshold = limits.max_drawdown_pct * 0.8;

        let (severity, message) = if drawdown >= limits.max_drawdown_pct {
            (
                Severity::Critical,
                format!(
                    "Drawdown {:.2}% EXCEEDED limit {:.2}% for account {}",
                    drawdown * 100.0,
                    limits.max_drawdown_pct * 100.0,
                    account_id
                ),
            )
        } else if drawdown >= warning_threshold {
            (
                Severity::High,
                format!(
                    "Drawdown {:.2}% approaching limit {:.2}% for account {} (warning at {:.2}%)",
                    drawdown * 100.0,
                    limits.max_drawdown_pct * 100.0,
                    account_id,
                    warning_threshold * 100.0
                ),
            )
        } else if drawdown >= limits.max_drawdown_pct * 0.5 {
            (
                Severity::Medium,
                format!(
                    "Drawdown {:.2}% for account {} at 50% of limit",
                    drawdown * 100.0,
                    account_id
                ),
            )
        } else {
            return;
        };

        let alert = RiskAlert {
            alert_id: Uuid::new_v4().to_string(),
            alert_type: "drawdown_warning".to_string(),
            severity: severity.as_str().to_string(),
            message,
            current_value: drawdown,
            threshold: limits.max_drawdown_pct,
            timestamp_ns: chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0),
        };

        if let Err(e) = self.alert_tx.send(alert) {
            warn!("No active alert subscribers: {}", e);
        }
    }
}

impl Default for RiskEngine {
    fn default() -> Self {
        Self::new()
    }
}

#[tonic::async_trait]
impl RiskService for RiskEngine {
    async fn pre_trade_check(
        &self,
        request: Request<proto::PreTradeCheckRequest>,
    ) -> Result<Response<proto::PreTradeCheckResponse>, Status> {
        let req = request.into_inner();

        let state = AccountState {
            equity: 1_000_000.0,
            peak_value: 1_050_000.0,
            pnl_today: 0.0,
            open_positions: vec![],
            gross_exposure: 0.0,
        };

        let order = PreTradeCheck {
            account_id: req.account_id.clone(),
            symbol: req.symbol,
            side: req.side,
            quantity: req.quantity,
            price: req.price,
            strategy_id: req.strategy_id,
        };

        let result = self.pre_trade_check(&state, &order);

        info!(
            "Pre-trade check for account {}: approved={}",
            req.account_id, result.approved
        );

        Ok(Response::new(proto::PreTradeCheckResponse {
            approved: result.approved,
            rejection_reasons: result.rejection_reasons,
            current_exposure: result.current_exposure,
            max_exposure: result.max_exposure,
            current_drawdown: result.current_drawdown,
            max_drawdown: result.max_drawdown,
            concentration_pct: result.concentration_pct,
            max_concentration_pct: result.max_concentration_pct,
        }))
    }

    async fn get_risk_metrics(
        &self,
        request: Request<proto::RiskMetricsRequest>,
    ) -> Result<Response<proto::RiskMetricsResponse>, Status> {
        let req = request.into_inner();

        let metrics = self
            .get_risk_metrics(&req.account_id)
            .unwrap_or_default();

        let now_ns = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0);

        Ok(Response::new(proto::RiskMetricsResponse {
            var_95: metrics.var_95,
            var_99: metrics.var_99,
            cvar_95: metrics.cvar_95,
            max_drawdown: metrics.max_drawdown,
            sharpe_ratio: metrics.sharpe_ratio,
            sortino_ratio: metrics.sortino_ratio,
            beta: metrics.beta,
            correlation: metrics.correlation,
            leverage: metrics.leverage,
            gross_exposure: metrics.gross_exposure,
            net_exposure: metrics.net_exposure,
            timestamp_ns: now_ns,
        }))
    }

    type StreamRiskAlertsStream =
        tokio_stream::wrappers::ReceiverStream<Result<proto::RiskAlert, Status>>;

    async fn stream_risk_alerts(
        &self,
        request: Request<proto::StreamRiskAlertsRequest>,
    ) -> Result<Response<Self::StreamRiskAlertsStream>, Status> {
        let req = request.into_inner();
        let account_id = req.account_id;
        let alert_types: Vec<String> = req.alert_types;
        let mut rx = self.stream_risk_alerts();
        let (tx, rx_out) = tokio::sync::mpsc::channel(256);

        tokio::spawn(async move {
            loop {
                match rx.recv().await {
                    Ok(alert) => {
                        let type_match = alert_types.is_empty()
                            || alert_types.contains(&alert.alert_type);

                        if !type_match {
                            continue;
                        }

                        let proto_alert = proto::RiskAlert {
                            alert_id: alert.alert_id,
                            alert_type: alert.alert_type,
                            severity: alert.severity,
                            message: alert.message,
                            current_value: alert.current_value,
                            threshold: alert.threshold,
                            timestamp_ns: alert.timestamp_ns,
                        };

                        if tx.send(Ok(proto_alert)).await.is_err() {
                            break;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        warn!("Alert stream lagged, skipped {} alerts", n);
                    }
                    Err(broadcast::error::RecvError::Closed) => {
                        info!("Alert broadcast channel closed for account {}", account_id);
                        break;
                    }
                }
            }
        });

        Ok(Response::new(tokio_stream::wrappers::ReceiverStream::new(
            rx_out,
        )))
    }

    async fn set_risk_limits(
        &self,
        request: Request<proto::SetRiskLimitsRequest>,
    ) -> Result<Response<proto::SetRiskLimitsResponse>, Status> {
        let req = request.into_inner();

        let limits = RiskLimits {
            max_position_pct: req.max_position_pct,
            max_drawdown_pct: req.max_drawdown_pct,
            max_daily_loss_pct: req.max_daily_loss_pct,
            max_concentration_pct: req.max_concentration_pct,
            max_leverage: req.max_leverage,
            max_open_trades: req.max_open_trades as u32,
        };

        match self.set_risk_limits(&req.account_id, limits) {
            Ok(()) => {
                info!("Risk limits updated for account {}", req.account_id);
                Ok(Response::new(proto::SetRiskLimitsResponse {
                    success: true,
                    message: format!("Limits updated for account {}", req.account_id),
                }))
            }
            Err(e) => {
                error!(
                    "Failed to set risk limits for account {}: {}",
                    req.account_id, e
                );
                Ok(Response::new(proto::SetRiskLimitsResponse {
                    success: false,
                    message: e,
                }))
            }
        }
    }
}

pub async fn run_server(addr: &str, engine: RiskEngine) -> Result<(), Box<dyn std::error::Error>> {
    let addr = addr.parse()?;

    info!("Risk Engine gRPC server listening on {}", addr);

    tonic::transport::Server::builder()
        .add_service(proto::risk_service_server::RiskServiceServer::new(engine))
        .serve(addr)
        .await?;

    Ok(())
}
