"""Gunicorn production configuration for the SOC Sanitization Platform."""
from __future__ import annotations

import os

from sanitization_v2 import config as cfg

# The current processing engine uses background threads plus in-process live
# progress state. Keep exactly one Gunicorn worker until job execution is moved
# to an external worker queue. HTTP concurrency is provided by gthread threads.
workers = int(os.environ.get("SANIT_GUNICORN_WORKERS", "1"))
if workers != 1:
    raise RuntimeError(
        "SANIT_GUNICORN_WORKERS must remain 1 for v2.1. "
        "Use SANIT_GUNICORN_THREADS to control HTTP concurrency."
    )

threads = max(2, min(int(os.environ.get("SANIT_GUNICORN_THREADS", "4")), 16))
worker_class = "gthread"
bind = os.environ.get("SANIT_BIND", "0.0.0.0:8443")
timeout = int(os.environ.get("SANIT_GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.environ.get("SANIT_GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("SANIT_GUNICORN_KEEPALIVE", "5"))
max_requests = int(os.environ.get("SANIT_GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("SANIT_GUNICORN_MAX_REQUESTS_JITTER", "100"))
preload_app = False
capture_output = True
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("SANIT_LOG_LEVEL", "info")

# Gunicorn terminates TLS directly in the default deployment. Replace these
# files with the organization's internal-CA certificate/key in production.
cfg.ensure_selfsigned_certs()
certfile = os.environ.get("SANIT_TLS_CERT", str(cfg.BASE / "certs" / "cert.pem"))
keyfile = os.environ.get("SANIT_TLS_KEY", str(cfg.BASE / "certs" / "key.pem"))
