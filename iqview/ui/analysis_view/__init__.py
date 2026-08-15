"""
Shared 1D analysis view foundation for IQView popup tabs (Time Domain, Frequency Domain).
Provides unified UI scaffolding, zoom/pan navigation, 1D marker engine, and region statistics.
"""

from .base_view import BaseAnalysisView
from .marker_manager import AnalysisMarkerMixin
from .statistics import AnalysisStatsMixin

__all__ = [
    'BaseAnalysisView',
    'AnalysisMarkerMixin',
    'AnalysisStatsMixin',
]
