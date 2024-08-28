"""
A factory class for Qt GUI with iplotlib is implemented in this module.
"""

# Author: Jaswant Sai Panchumarti

from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class InvalidBackend(Exception):
    pass


class IplotQtCanvasFactory:
    """
    A factory class that returns an appropriate backend subclass of IplotQtCanvas.
    """

    @staticmethod
    def new(backend: str, *args, **kwargs) -> IplotQtCanvas:
        """
        The backend can be any one of "matplotlib", "mpl", "mplot", "mplib" for matplotlib.
        For VTK, the backend can be "vtk".
        .. note :: This function is case-insensitive. It converts to lower case.
        """
        if backend.lower() in ["matplotlib", "mpl", "mplot", "mplib"]:
            from iplotlib.impl.matplotlib.qt import QtMatplotlibCanvas
            return QtMatplotlibCanvas(*args, **kwargs)
        elif backend.lower() in ["vtk"]:
            from iplotlib.impl.vtk.qt import QtVTKCanvas
            return QtVTKCanvas(*args, **kwargs)
        else:
            logger.error(f"Unrecognized or unsupported backend: {backend}. Available backend: matplotlib, vtk")
            raise InvalidBackend
