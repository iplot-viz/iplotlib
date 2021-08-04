import os
from vtkmodules import vtkRenderingOpenGL2

def platform_is_headless() -> bool:
    return os.getenv("DISPLAY") is None

def vtk_is_headless() -> bool:
    return platform_is_headless() or \
        not hasattr(vtkRenderingOpenGL2, "vtkXOpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkWin32OpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkCocoaOpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkIOSRenderWindow")
