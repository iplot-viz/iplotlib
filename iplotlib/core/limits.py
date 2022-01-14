from dataclasses import dataclass, field
from typing import List, Any
from weakref import ref

@dataclass
class IplAxisLimits:
    begin: Any = None,
    end: Any = None
    axes_ref: ref = None


@dataclass
class IplPlotViewLimits:
    axes_ranges: List[IplAxisLimits] = field(default_factory=list)
    plot_ref: ref = None