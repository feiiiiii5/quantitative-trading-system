ARG BASE_IMAGE=python:3.12-slim
ARG CUDA_BASE=nvidia/cuda:12.4.1-runtime-ubuntu22.04

FROM ${CUDA_BASE} AS gpu-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python3.12 -m pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM ${BASE_IMAGE} AS cpu-builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install \
    $(grep -v "cupy" requirements.txt)

FROM ${BASE_IMAGE} AS runtime

LABEL maintainer="quantcore-team"
LABEL service="backtest-engine"
LABEL description="Institutional-grade tick-level backtesting engine with GPU acceleration"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=cpu-builder /install /usr/local

WORKDIR /app

COPY generated/ generated/
COPY quantcore_backtest/ quantcore_backtest/
COPY main.py .

EXPOSE 50056

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import grpc; ch=grpc.insecure_channel('localhost:50056'); ch.close()" || exit 1

CMD ["python", "main.py"]


FROM ${CUDA_BASE} AS gpu-runtime

LABEL maintainer="quantcore-team"
LABEL service="backtest-engine-gpu"
LABEL description="Backtest Engine with CUDA GPU acceleration"

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=gpu-builder /install /usr/local

WORKDIR /app

COPY generated/ generated/
COPY quantcore_backtest/ quantcore_backtest/
COPY main.py .

EXPOSE 50056

CMD ["python3.12", "main.py"]
