"""
Telemetry setup — structured logging (no Azure).

App Insights / azure.monitor was removed in the Azure-off migration (#14). Observability
now rests on two things that need no paid infra:
  - structured request logs (correlation id + latency) via ObservabilityMiddleware,
    visible in the process stdout/stderr (and thus Fly log streams).
  - Langfuse for AI traces (see src/tracing.py).

ponytail: logs + Langfuse are enough for the demo. Upgrade path if richer metrics are
needed: point OTEL at a free-tier backend (Grafana Cloud / Better Stack) behind this
same setup function — callers won't change.
"""
import logging

logger = logging.getLogger("brand-guardian-telemetry")


def setup_telemetry() -> None:
    """Configure structured logging. Kept as a named entry point so the app's startup
    call site is stable regardless of the observability backend behind it."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("Telemetry: structured logging enabled (Langfuse handles AI traces).")
