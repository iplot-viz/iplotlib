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

        # supported_backends = {}
        #
        # try:
        #     file_path = str(files('mint').joinpath('mybackends.cfg'))
        #     with open(file_path, 'r') as file:
        #         backends = json.load(file)
        #         for key, value in backends.items():
        #             try:
        #                 module = importlib.import_module(value['pymodule'])
        #                 imported_class = getattr(module, value['class'])
        #                 supported_backends[imported_class.alias] = imported_class
        #             except Exception as e:
        #                 logger.error(f"Error loading Backend {key} -> {e}")
        #
        # except Exception as e:
        #     logger.error(f"Error loading Backends config file ->{e}")
        #
        # qt_backend = supported_backends.get(impl.lower())
        #
        # if qt_backend is not None:
        #
        # else:
        #     raise Exception(f"'{impl}' is not a valid backend")