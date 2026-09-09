#!/usr/bin/env python3
"""Compatibility entry point for the modular Sanitization Platform v2 backend."""
from sanitization_v2.app import app, main
from sanitization_v2.ui_extension import register_ui_extension

register_ui_extension(app)

if __name__ == "__main__":
    main()
