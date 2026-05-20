"""
Infrastructure for writting tests with a full blown Qt Application involving interaction and event processing
"""

from .qAppTestAdapter import QAppTestAdapter
from .qAppSingleton import ensure_qapp
from .imageCompare import compare_pixmap_to_baseline

__all__ = ['QAppTestAdapter', 'ensure_qapp', 'compare_pixmap_to_baseline']
