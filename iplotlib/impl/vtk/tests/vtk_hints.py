import os

import matplotlib
from vtkmodules import vtkRenderingOpenGL2

def platform_is_headless() -> bool:
    return os.getenv("DISPLAY") is None

def vtk_is_headless() -> bool:
    return platform_is_headless() or \
        not hasattr(vtkRenderingOpenGL2, "vtkXOpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkWin32OpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkCocoaOpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkIOSRenderWindow")

def matplotlib_is_headless() -> bool:
    headless_backends = {"Agg", "Cairo", "PDF", "SVG", "PS"}
    current_backend = matplotlib.get_backend()
    return current_backend in headless_backends