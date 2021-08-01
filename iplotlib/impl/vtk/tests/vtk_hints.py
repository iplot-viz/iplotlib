from vtkmodules import vtkRenderingOpenGL2


def vtk_is_headless() -> bool:
    return \
        not hasattr(vtkRenderingOpenGL2, "vtkXOpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkWin32OpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkCocoaOpenGLRenderWindow") and \
        not hasattr(vtkRenderingOpenGL2, "vtkIOSRenderWindow")
