"""Structured JSON logging with mandatory trace context."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from obs.redact import redact_obj

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
account_id_var: ContextVar[str] = ContextVar("account_id", default="-")
run_id_var: ContextVar[str] = ContextVar("run_id", default="-")
step_var: ContextVar[str] = ContextVar("step", default="-")
worker_id_var: ContextVar[str] = ContextVar("worker_id", default="-")


def _inject_context(_logger, _name, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.setdefault("trace_id", trace_id_var.get())
    event_dict.setdefault("account_id", account_id_var.get())
    event_dict.setdefault("run_id", run_id_var.get())
    event_dict.setdefault("step", step_var.get())
    event_dict.setdefault("worker_id", worker_id_var.get())
    return event_dict


def _redact(_logger, _name, event_dict: dict[str, Any]) -> dict[str, Any]:
    return redact_obj(event_dict)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), 20))
    renderer = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), 20)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "yelp_factory"):
    return structlog.get_logger(name)


class bind_context:
    """Bind trace/account/run identifiers for the duration of a block."""

    def __init__(self, **kwargs: str):
        self._kwargs = kwargs
        self._tokens = []

    def __enter__(self):
        setters = {
            "trace_id": trace_id_var,
            "account_id": account_id_var,
            "run_id": run_id_var,
            "step": step_var,
            "worker_id": worker_id_var,
        }
        for key, value in self._kwargs.items():
            if key in setters:
                self._tokens.append((setters[key], setters[key].set(value)))
        return self

    def __exit__(self, *exc_info):
        for var, token in reversed(self._tokens):
            var.reset(token)
        self._tokens.clear()
