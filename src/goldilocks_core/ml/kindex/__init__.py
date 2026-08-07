"""K-index inference boundary.

Re-exports the public k-index prediction entry point from ``.inference``.
"""

from __future__ import annotations

from .inference import predict_kindex

__all__ = ["predict_kindex"]
