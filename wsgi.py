"""WSGI entry point for Gunicorn and compatible WSGI hosts."""
from __future__ import annotations

import sys
from pathlib import Path

project_home = Path(__file__).parent.resolve()
if str(project_home) not in sys.path:
    sys.path.insert(0, str(project_home))

from sanitization_v2.app import app as application  # noqa: E402
from sanitization_v2.ui_extension import register_ui_extension  # noqa: E402

register_ui_extension(application)

# Optional alias used by some WSGI hosts.
app = application
