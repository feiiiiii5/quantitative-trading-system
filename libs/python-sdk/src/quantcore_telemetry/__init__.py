from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

_OTEL_ENABLED: bool = False
_tracer: Any = None
_meter: Any = None


def init_telemetry(
    service_name: str,
    endpoint: str = "http://tempo:4317",
    enable_metrics: bool = True,
) -> None:
    global _OTEL_ENABLED, _tracer, _meter
    try:
        from opentelemetry import trace, metrics
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint)))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)

        if enable_metrics:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint))
            meter_provider = MeterProvider(resource=resource, readers=[reader])
            metrics.set_meter_provider(meter_provider)
            _meter = metrics.get_meter(service_name)

        _OTEL_ENABLED = True
        logger.info("OpenTelemetry initialized: service=%s endpoint=%s", service_name, endpoint)
    except ImportError:
        logger.warning("opentelemetry packages not installed, tracing disabled")
    except Exception as e:
        logger.warning("OpenTelemetry init failed: %s", e)


@dataclass
class SpanContext:
    trace_id: str = ""
    span_id: str = ""
    operation: str = ""
    start_time_ns: int = 0

    def elapsed_ms(self) -> float:
        if self.start_time_ns == 0:
            return 0.0
        return (time.time_ns() - self.start_time_ns) / 1e6


@contextmanager
def trace_span(
    operation: str,
    attributes: Optional[dict[str, Any]] = None,
) -> Generator[SpanContext, None, None]:
    ctx = SpanContext(operation=operation, start_time_ns=time.time_ns())

    if _tracer is not None:
        with _tracer.start_as_current_span(operation) as span:
            if attributes:
                for k, v in attributes.items():
                    span.set_attribute(k, str(v))
            ctx.trace_id = format(span.get_span_context().trace_id, "032x")
            ctx.span_id = format(span.get_span_context().span_id, "016x")
            yield ctx
    else:
        yield ctx


def record_metric(name: str, value: float, attributes: Optional[dict[str, str]] = None) -> None:
    if _meter is not None:
        counter = _meter.create_counter(name)
        counter.add(value, attributes or {})
    else:
        logger.debug("Metric: %s = %s %s", name, value, attributes or "")


def is_enabled() -> bool:
    return _OTEL_ENABLED


__all__ = [
    "init_telemetry",
    "trace_span",
    "record_metric",
    "is_enabled",
    "SpanContext",
]
