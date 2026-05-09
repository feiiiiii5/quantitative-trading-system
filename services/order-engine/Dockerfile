FROM rust:1.80-slim AS builder
WORKDIR /app

COPY proto/ /proto/
COPY services/order-engine/Cargo.toml services/order-engine/Cargo.lock* ./
COPY services/order-engine/build.rs ./
COPY services/order-engine/src/ src/

RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/order-engine-server /usr/local/bin/
EXPOSE 50052
CMD ["order-engine-server"]
