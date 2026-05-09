mod proto {
    tonic::include_proto!("quantcore.order.v1");
}

use quantcore_order_engine::engine::{EngineError, NewOrder, OrderEngine, OrderEvent};
use quantcore_order_engine::order::{OrderSide, OrderStatus, OrderType};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status};
use tracing::info;

fn domain_side_to_proto(side: OrderSide) -> i32 {
    match side {
        OrderSide::Buy => proto::OrderSide::Buy as i32,
        OrderSide::Sell => proto::OrderSide::Sell as i32,
    }
}

fn proto_side_to_domain(value: i32) -> Option<OrderSide> {
    match proto::OrderSide::try_from(value).ok()? {
        proto::OrderSide::Buy => Some(OrderSide::Buy),
        proto::OrderSide::Sell => Some(OrderSide::Sell),
        _ => None,
    }
}

fn domain_type_to_proto(order_type: OrderType) -> i32 {
    match order_type {
        OrderType::Market => proto::OrderType::Market as i32,
        OrderType::Limit => proto::OrderType::Limit as i32,
        OrderType::Stop => proto::OrderType::Stop as i32,
        OrderType::StopLimit => proto::OrderType::StopLimit as i32,
    }
}

fn proto_type_to_domain(value: i32) -> Option<OrderType> {
    match proto::OrderType::try_from(value).ok()? {
        proto::OrderType::Market => Some(OrderType::Market),
        proto::OrderType::Limit => Some(OrderType::Limit),
        proto::OrderType::Stop => Some(OrderType::Stop),
        proto::OrderType::StopLimit => Some(OrderType::StopLimit),
        _ => None,
    }
}

fn domain_status_to_proto(status: OrderStatus) -> i32 {
    match status {
        OrderStatus::Pending => proto::OrderStatus::Pending as i32,
        OrderStatus::Accepted => proto::OrderStatus::Accepted as i32,
        OrderStatus::PartiallyFilled => proto::OrderStatus::PartiallyFilled as i32,
        OrderStatus::Filled => proto::OrderStatus::Filled as i32,
        OrderStatus::Cancelled => proto::OrderStatus::Cancelled as i32,
        OrderStatus::Rejected => proto::OrderStatus::Rejected as i32,
    }
}

fn engine_error_to_status(err: EngineError) -> Status {
    match err {
        EngineError::Validation(msg) => Status::invalid_argument(msg),
        EngineError::NotFound(id) => Status::not_found(format!("Order not found: {}", id)),
        EngineError::CannotCancel(reason) => Status::failed_precondition(reason),
        EngineError::StoreAtCapacity => Status::resource_exhausted("Idempotency store at capacity"),
    }
}

struct OrderEngineServiceImpl {
    engine: OrderEngine,
}

#[tonic::async_trait]
impl proto::order_service_server::OrderService for OrderEngineServiceImpl {
    async fn submit_order(
        &self,
        request: Request<proto::SubmitOrderRequest>,
    ) -> Result<Response<proto::SubmitOrderResponse>, Status> {
        let req = request.into_inner();

        let side = proto_side_to_domain(req.side)
            .ok_or_else(|| Status::invalid_argument(format!("invalid order side: {}", req.side)))?;

        let order_type = proto_type_to_domain(req.order_type)
            .ok_or_else(|| Status::invalid_argument(format!("invalid order type: {}", req.order_type)))?;

        let new_order = NewOrder {
            client_order_id: req.client_order_id,
            symbol: req.symbol,
            side,
            order_type,
            quantity: req.quantity,
            price: req.price,
            stop_price: req.stop_price,
            strategy_id: req.strategy_id,
            account_id: req.account_id,
        };

        let result = self
            .engine
            .submit_order(new_order)
            .map_err(engine_error_to_status)?;

        Ok(Response::new(proto::SubmitOrderResponse {
            order_id: result.order_id,
            client_order_id: result.client_order_id,
            status: domain_status_to_proto(result.status),
            reject_reason: result.reject_reason,
            timestamp_ns: result.timestamp_ns,
        }))
    }

    async fn cancel_order(
        &self,
        request: Request<proto::CancelOrderRequest>,
    ) -> Result<Response<proto::CancelOrderResponse>, Status> {
        let req = request.into_inner();

        let result = if !req.order_id.is_empty() {
            self.engine.cancel_order(&req.order_id)
        } else if !req.client_order_id.is_empty() {
            self.engine.cancel_order_by_client_id(&req.client_order_id)
        } else {
            return Err(Status::invalid_argument(
                "either order_id or client_order_id must be provided",
            ));
        }
        .map_err(engine_error_to_status)?;

        Ok(Response::new(proto::CancelOrderResponse {
            success: result.success,
            order_id: result.order_id,
            message: result.message,
        }))
    }

    async fn get_order_status(
        &self,
        request: Request<proto::OrderStatusRequest>,
    ) -> Result<Response<proto::OrderStatusResponse>, Status> {
        let req = request.into_inner();

        let order_id = if req.order_id.is_empty() {
            None
        } else {
            Some(req.order_id.as_str())
        };
        let client_order_id = if req.client_order_id.is_empty() {
            None
        } else {
            Some(req.client_order_id.as_str())
        };

        let status = self
            .engine
            .get_order_status(order_id, client_order_id)
            .ok_or_else(|| Status::not_found("Order not found"))?;

        Ok(Response::new(proto::OrderStatusResponse {
            order_id: status.order_id,
            client_order_id: status.client_order_id,
            symbol: status.symbol,
            side: domain_side_to_proto(status.side),
            order_type: domain_type_to_proto(status.order_type),
            status: domain_status_to_proto(status.status),
            quantity: status.quantity,
            filled_quantity: status.filled_quantity,
            avg_fill_price: status.avg_fill_price,
            commission: status.commission,
            timestamp_ns: status.timestamp_ns,
        }))
    }

    type StreamOrderUpdatesStream = ReceiverStream<Result<proto::OrderUpdate, Status>>;

    async fn stream_order_updates(
        &self,
        request: Request<proto::StreamOrderUpdatesRequest>,
    ) -> Result<Response<Self::StreamOrderUpdatesStream>, Status> {
        let req = request.into_inner();
        let account_id_filter = if req.account_id.is_empty() {
            None
        } else {
            Some(req.account_id)
        };
        let symbol_filters = req.symbol_filters;
        let mut rx = self.engine.stream_order_updates();

        let (tx, rx_out) = tokio::sync::mpsc::channel(256);

        tokio::spawn(async move {
            loop {
                match rx.recv().await {
                    Ok(event) => {
                        if let Some(ref filter) = account_id_filter {
                            if event.account_id() != filter.as_str() {
                                continue;
                            }
                        }
                        if !symbol_filters.is_empty()
                            && !symbol_filters.contains(&event.symbol().to_string())
                        {
                            continue;
                        }

                        let order_id = event.order_id().to_string();
                        let event_type = event.event_type().to_string();

                        let (status, filled_quantity, fill_price, commission, timestamp_ns) =
                            match &event {
                                OrderEvent::Submitted {
                                    status,
                                    timestamp_ns,
                                    ..
                                } => (*status, 0, 0.0, 0.0, *timestamp_ns),
                                OrderEvent::Filled {
                                    status,
                                    filled_quantity,
                                    fill_price,
                                    commission,
                                    timestamp_ns,
                                    ..
                                } => (
                                    *status,
                                    *filled_quantity,
                                    *fill_price,
                                    *commission,
                                    *timestamp_ns,
                                ),
                                OrderEvent::Cancelled {
                                    status,
                                    timestamp_ns,
                                    ..
                                } => (*status, 0, 0.0, 0.0, *timestamp_ns),
                                OrderEvent::Rejected {
                                    status,
                                    timestamp_ns,
                                    ..
                                } => (*status, 0, 0.0, 0.0, *timestamp_ns),
                            };

                        let update = proto::OrderUpdate {
                            order_id,
                            status: domain_status_to_proto(status),
                            filled_quantity,
                            fill_price,
                            commission,
                            timestamp_ns,
                            event_type,
                        };

                        if tx.send(Ok(update)).await.is_err() {
                            break;
                        }
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                        tracing::warn!(skipped = n, "Order update stream lagged");
                        continue;
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                        break;
                    }
                }
            }
        });

        Ok(Response::new(ReceiverStream::new(rx_out)))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .json()
        .init();

    let addr = std::env::var("ORDER_ENGINE_ADDR")
        .unwrap_or_else(|_| "0.0.0.0:50052".to_string());

    info!("Starting QuantCore Order Engine v0.1.0 on {}", addr);

    let engine = OrderEngine::new();
    let service_impl = OrderEngineServiceImpl { engine };

    let addr_parsed: std::net::SocketAddr = addr.parse()?;

    tonic::transport::Server::builder()
        .add_service(proto::order_service_server::OrderServiceServer::new(service_impl))
        .serve(addr_parsed)
        .await?;

    Ok(())
}
