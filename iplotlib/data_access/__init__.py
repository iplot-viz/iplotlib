"""
Data access infrastructure for iplotlib: real-time streaming and data access in worker processes.
"""

from .access_pool import AccessPool
from .streamer import CanvasStreamer

__all__ = ["AccessPool", "CanvasStreamer"]
