FROM rust:1.80-slim AS builder
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY build.rs ./
COPY src/ src/
COPY ../../proto/ /proto/
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/risk-engine-server /usr/local/bin/
EXPOSE 50053
CMD ["risk-engine-server"]
