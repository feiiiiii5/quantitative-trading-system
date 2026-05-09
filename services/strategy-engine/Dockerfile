FROM python:3.12-slim AS builder

WORKDIR /build

COPY services/strategy-engine/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY proto/ /app/proto/
COPY services/strategy-engine/proto_compile.sh .
COPY services/strategy-engine/quantcore_strategy/ quantcore_strategy/

RUN mkdir -p /app/quantcore_strategy/generated \
    && touch /app/quantcore_strategy/generated/__init__.py \
    && bash proto_compile.sh

COPY services/strategy-engine/main.py .

EXPOSE 50054

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('localhost',50054)); s.close()" || exit 1

CMD ["python", "main.py"]
