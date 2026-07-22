"""Telemetry spine — pydantic-ai OpenTelemetry spans exported to Langfuse.

pydantic-ai emits OTel spans for every LLM call and tool call when instrumented.
Langfuse ingests OTLP directly, so we point an OTLP exporter at Langfuse's endpoint
and turn on instrumentation. Shared cloud tracing (D7, now Langfuse instead of Phoenix)
so Vinay, Shubham, and mentors see the same runs, sliceable by system/model/instance.

Activation is config-gated (design mirrors the model layer): with no Langfuse keys set,
`setup_telemetry()` is a no-op and we rely on the keyless local trace (agent/trace.py).
Set RCA_LANGFUSE_PUBLIC_KEY + RCA_LANGFUSE_SECRET_KEY (+ RCA_LANGFUSE_HOST) to light it up.

Requires: opentelemetry-sdk, opentelemetry-exporter-otlp-proto-http (install on enable).
"""

from __future__ import annotations

import base64

from .config import Settings, get_settings

_STATE = {"done": False, "enabled": False}  # configure once per process (Settings is unhashable)


def setup_telemetry(settings: Settings | None = None) -> bool:
    """Configure OTel -> Langfuse and instrument pydantic-ai. Returns True if enabled.

    Idempotent: safe to call at the start of every run."""
    if _STATE["done"]:
        return _STATE["enabled"]
    settings = settings or get_settings()
    _STATE["done"] = True
    if not settings.has_langfuse:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        raise RuntimeError(
            "Langfuse telemetry needs OTel packages. Install:\n"
            "  pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
        ) from e

    auth = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()
    exporter = OTLPSpanExporter(
        endpoint=f"{settings.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )
    provider = TracerProvider(resource=Resource.create({"service.name": "product-rca-agent"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    from pydantic_ai import Agent
    Agent.instrument_all()  # every agent emits LLM + tool spans from here on
    _STATE["enabled"] = True
    return True
