"""Shared slowapi Limiter instance.

Lives in its own module so route files can `from app.core.rate_limit import limiter`
and apply `@limiter.limit(...)` decorators without an import cycle through main.py.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
