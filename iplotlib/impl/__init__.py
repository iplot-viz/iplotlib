from iplotlib.core.canvas import Canvas
from iplotlib.impl.vtk import VTKCanvas

class CanvasFactory:
    @staticmethod
    def new(backend: str, *args, **kwargs) -> Canvas:
        if backend.lower() in ["matplotlib", "mpl", "mplot", "mplib"]:
            return None
        elif backend.lower() in ["vtk"]:
            return VTKCanvas(*args, **kwargs)
