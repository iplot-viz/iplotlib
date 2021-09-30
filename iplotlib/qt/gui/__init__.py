from .iplotQtCanvas import IplotQtCanvas

class IplotQtCanvasFactory:
    def new(backend: str, *args, **kwargs) -> IplotQtCanvas:
        if backend.lower() in ["matplotlib", "mpl", "mplot", "mplib"]:
            return None
        elif backend.lower() in ["vtk"]:
            from iplotlib.impl.vtk.qt import QtVTKCanvas
            return QtVTKCanvas(*args, **kwargs)
