"""The page now lives in macro.site; this keeps the old import path working."""

from macro.site import build_dashboard
from macro.site.payload import _yoy_pct

__all__ = ["build_dashboard", "_yoy_pct"]
