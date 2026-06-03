"""Prometheus metric definitions for the observability middleware."""

from prometheus_client import Counter, Histogram, Gauge

REQUESTS_TOTAL = Counter(
    "requests_total",
    "Total HTTP requests",
    ["method", "handler", "status"],
)

REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "handler"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

ACTIVE_CONNECTIONS = Gauge(
    "active_connections",
    "Active real-time connections (Socket.IO fallback)",
)
