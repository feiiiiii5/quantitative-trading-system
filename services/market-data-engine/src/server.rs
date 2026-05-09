use crate::snapshot::MarketDataSnapshot;
use tokio::net::TcpListener;
use tonic::transport::Server;
use tracing::info;

pub mod proto {
    tonic::include_proto!("quantcore.marketdata.v1");
}

use proto::market_data_service_server::MarketDataServiceServer;

pub struct MarketDataServiceImpl {
    snapshot: MarketDataSnapshot,
}

#[tonic::async_trait]
impl proto::market_data_service_server::MarketDataService for MarketDataServiceImpl {
    async fn get_realtime(
        &self,
        request: tonic::Request<proto::RealtimeRequest>,
    ) -> Result<tonic::Response<proto::RealtimeResponse>, tonic::Status> {
        let req = request.into_inner();
        let quotes = self.snapshot.get_quotes(&req.symbols);
        let proto_quotes: Vec<proto::RealtimeQuote> = quotes
            .into_iter()
            .map(|q| proto::RealtimeQuote {
                symbol: q.symbol,
                price: q.price,
                open: q.open,
                high: q.high,
                low: q.low,
                close: q.close,
                prev_close: q.prev_close,
                volume: q.volume,
                amount: q.amount,
                bid_price: q.bid_price,
                ask_price: q.ask_price,
                bid_volume: q.bid_volume,
                ask_volume: q.ask_volume,
                change_pct: q.change_pct,
                turnover_rate: q.turnover_rate,
                timestamp_ns: q.timestamp_ns,
            })
            .collect();

        let now_ns = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0);
        Ok(tonic::Response::new(proto::RealtimeResponse {
            quotes: proto_quotes,
            timestamp_ns: now_ns,
        }))
    }

    async fn get_history(
        &self,
        _request: tonic::Request<proto::HistoryRequest>,
    ) -> Result<tonic::Response<proto::HistoryResponse>, tonic::Status> {
        Err(tonic::Status::unimplemented("Use Python backtest service for history data"))
    }

    type StreamRealtimeStream = tokio_stream::wrappers::ReceiverStream<
        Result<proto::RealtimeUpdate, tonic::Status>,
    >;

    async fn stream_realtime(
        &self,
        request: tonic::Request<proto::StreamRealtimeRequest>,
    ) -> Result<tonic::Response<Self::StreamRealtimeStream>, tonic::Status> {
        let req = request.into_inner();
        let symbols = req.symbols;
        let mut rx = self.snapshot.subscribe();
        let (tx, rx_out) = tokio::sync::mpsc::channel(256);

        tokio::spawn(async move {
            loop {
                match rx.recv().await {
                    Ok(event) => match event {
                        crate::snapshot::MarketDataEvent::QuoteUpdate(q) => {
                            if symbols.is_empty() || symbols.contains(&q.symbol) {
                                let update = proto::RealtimeUpdate {
                                    quote: Some(proto::RealtimeQuote {
                                        symbol: q.symbol,
                                        price: q.price,
                                        open: q.open,
                                        high: q.high,
                                        low: q.low,
                                        close: q.close,
                                        prev_close: q.prev_close,
                                        volume: q.volume,
                                        amount: q.amount,
                                        bid_price: q.bid_price,
                                        ask_price: q.ask_price,
                                        bid_volume: q.bid_volume,
                                        ask_volume: q.ask_volume,
                                        change_pct: q.change_pct,
                                        turnover_rate: q.turnover_rate,
                                        timestamp_ns: q.timestamp_ns,
                                    }),
                                    event_type: "quote_update".to_string(),
                                };
                                if tx.send(Ok(update)).await.is_err() {
                                    break;
                                }
                            }
                        }
                        _ => {}
                    },
                    Err(_) => break,
                }
            }
        });

        Ok(tonic::Response::new(
            tokio_stream::wrappers::ReceiverStream::new(rx_out),
        ))
    }

    async fn get_order_book(
        &self,
        request: tonic::Request<proto::OrderBookRequest>,
    ) -> Result<tonic::Response<proto::OrderBookResponse>, tonic::Status> {
        let req = request.into_inner();
        let book = self.snapshot.orderbooks.get(&req.symbol);
        match book {
            Some(b) => {
                let bids: Vec<proto::PriceLevel> = b
                    .bids
                    .iter()
                    .map(|l| proto::PriceLevel {
                        price: l.price,
                        quantity: l.quantity,
                        order_count: l.order_count,
                    })
                    .collect();
                let asks: Vec<proto::PriceLevel> = b
                    .asks
                    .iter()
                    .map(|l| proto::PriceLevel {
                        price: l.price,
                        quantity: l.quantity,
                        order_count: l.order_count,
                    })
                    .collect();
                Ok(tonic::Response::new(proto::OrderBookResponse {
                    symbol: req.symbol,
                    bids,
                    asks,
                    timestamp_ns: b.timestamp_ns,
                }))
            }
            None => Err(tonic::Status::not_found("Order book not found")),
        }
    }

    type SubscribeDepthStream = tokio_stream::wrappers::ReceiverStream<
        Result<proto::DepthUpdate, tonic::Status>,
    >;

    async fn subscribe_depth(
        &self,
        _request: tonic::Request<proto::DepthSubscriptionRequest>,
    ) -> Result<tonic::Response<Self::SubscribeDepthStream>, tonic::Status> {
        Err(tonic::Status::unimplemented("Depth subscription coming soon"))
    }
}

pub async fn run_server(addr: &str, snapshot: MarketDataSnapshot) -> Result<(), Box<dyn std::error::Error>> {
    let addr = addr.parse()?;
    let service = MarketDataServiceImpl { snapshot };

    info!("Market Data Engine gRPC server listening on {}", addr);

    Server::builder()
        .add_service(MarketDataServiceServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}
