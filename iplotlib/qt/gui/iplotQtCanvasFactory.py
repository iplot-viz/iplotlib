"""
A factory class that returns an appropriate backend subclass of IplotQtCanvas.
"""

# Author: Jaswant Sai Panchumarti

from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas

import iplotLogging.setupLogger as ls

logger = ls.get_logger(__name__)

class InvalidBackend(Exception):
    pass

class IplotQtCanvasFactory:
    def new(backend: str, *args, **kwargs) -> IplotQtCanvas:
        if backend.lower() in ["matplotlib", "mpl", "mplot", "mplib"]:
            from iplotlib.impl.matplotlib.qt import QtMatplotlibCanvas
            return QtMatplotlibCanvas(*args, **kwargs)
        elif backend.lower() in ["vtk"]:
            from iplotlib.impl.vtk.qt import QtVTKCanvas
            return QtVTKCanvas(*args, **kwargs)
        else:
            logger.error(f"Unrecognized or unsupported backend: {backend}. Available backend: matplotlib, vtk")
            raise InvalidBackend
