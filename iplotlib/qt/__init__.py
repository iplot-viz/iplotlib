from .qtPlotCanvas import QtPlotCanvas

class QtPlotCanvasFactory:
    def new(backend: str, *args, **kwargs) -> QtPlotCanvas:
        if backend.lower() in ["matplotlib", "mpl", "mplot", "mplib"]:
            return None
        elif backend.lower() in ["vtk"]:
            from iplotlib.impl.vtk.qt import QtVTKCanvas
            return QtVTKCanvas(*args, **kwargs)
