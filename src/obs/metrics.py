"""Prometheus metrics (section 12)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

signup_total = Counter("signup_total", "Signup attempts by result", ["result"])
signup_duration_seconds = Histogram(
    "signup_duration_seconds",
    "Wall time from browser start to ACTIVE",
    buckets=(30, 60, 90, 120, 180, 240, 300, 600),
)
step_failures_total = Counter("step_failures_total", "Step failures by code", ["code", "step"])
active_profiles = Gauge("active_profiles", "GPM profiles currently open")
proxy_health_ratio = Gauge("proxy_health_ratio", "Share of proxies with health=ok")
selector_miss_total = Counter("selector_miss_total", "Selector registry misses", ["key"])
queue_depth = Gauge("queue_depth", "Pending jobs in the queue")
warming_actions_total = Counter("warming_actions_total", "Warming actions executed", ["kind", "phase"])
