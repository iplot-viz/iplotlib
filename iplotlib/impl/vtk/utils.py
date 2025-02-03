import datetime
import numpy as np
import os
import shutil
from typing import Tuple, Union, Any

from vtkmodules.vtkCommonDataModel import vtkColor4d, vtkColor3d, vtkColor4ub, vtkColor3ub, vtkImageData
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkImagingCore import vtkImageDifference
from vtkmodules.vtkIOImage import vtkPNGReader, vtkJPEGReader, vtkPNGWriter, vtkJPEGWriter, vtkPostScriptWriter
from vtkmodules.vtkRenderingCore import vtkRenderWindow, vtkWindowToImageFilter

import logging

logger = logging.getLogger(__name__)
vtkColors = vtkNamedColors()


def get_color4d(color: str) -> Union[Tuple[float], Tuple[float, float, float, float]]:
    """See [VTKNamedColorPatches]
    (https://htmlpreview.github.io/?https://github.com/Kitware/vtk-examples/blob/gh-pages/VTKNamedColorPatches.html)
    for valid color names

    Args:
        color (str): a valid color name

    Returns:
        Tuple[float]: r, g, b, a (0. ... 1.)
    """
    if color[0] == "#" and len(color) == 7:
        color += "FF"
    if color[0] == "#" and len(color) == 9:
        # Convert hex string to RGBA
        return tuple(int(color[i:i + 2], 16) / 255 for i in range(1, 9, 2))
    c4d = vtkColor4d()
    vtkColors.GetColor(color, c4d)
    return c4d.GetRed(), c4d.GetGreen(), c4d.GetBlue(), c4d.GetAlpha()


def get_color4ub(color: str) -> Union[Tuple[int], Tuple[int, int, int, int]]:
    """See [VTKNamedColorPatches]
    (https://htmlpreview.github.io/?https://github.com/Kitware/vtk-examples/blob/gh-pages/VTKNamedColorPatches.html)
    for valid color names

    Args:
        color (str): a valid color name

    Returns:
        Tuple[int]: r, g, b, a (0 ... 255)
    """
    if color[0] == "#" and len(color) == 7:
        color += "FF"
    if color[0] == "#" and len(color) == 9:
        # Convert hex string to RGBA
        return tuple(int(color[i:i + 2], 16) for i in range(1, 9, 2))
    c4ub = vtkColor4ub()
    vtkColors.GetColor(color, c4ub)
    return c4ub.GetRed(), c4ub.GetGreen(), c4ub.GetBlue(), c4ub.GetAlpha()


def get_color3d(color: str) -> Union[Tuple[float], Tuple[float, float, float]]:
    """See [VTKNamedColorPatches]
    (https://htmlpreview.github.io/?https://github.com/Kitware/vtk-examples/blob/gh-pages/VTKNamedColorPatches.html)
    for valid color names

    Args:
        color (str): a valid color name

    Returns:
        Tuple[float]: r, g, b (0. ... 1.)
    """
    if color[0] == "#" and len(color) == 7:
        # Convert hex string to RGBA
        return tuple(int(color[i:i + 2], 16) / 255 for i in range(1, 7, 2))
    c3d = vtkColor3d()
    vtkColors.GetColor(color, c3d)
    return c3d.GetRed(), c3d.GetGreen(), c3d.GetBlue()


def get_color3ub(color: str) -> Union[Tuple[int], Tuple[int, int, int]]:
    """See [VTKNamedColorPatches]
    (https://htmlpreview.github.io/?https://github.com/Kitware/vtk-examples/blob/gh-pages/VTKNamedColorPatches.html)
    for valid color names

    Args:
        color (str): a valid color name

    Returns:
        Tuple[int]: r, g, b (0 ... 255)
    """
    if color[0] == "#" and len(color) == 7:
        # Convert hex string to RGBA
        return tuple(int(color[i:i + 2], 16) for i in range(1, 7, 2))
    c3ub = vtkColor3ub()
    vtkColors.GetColor(color, c3ub)
    return c3ub.GetRed(), c3ub.GetGreen(), c3ub.GetBlue()


def read_image(fname: str) -> vtkImageData:
    reader = None
    if fname.endswith("png"):
        reader = vtkPNGReader()
    elif fname.endswith("jpg") or fname.endswith("jpeg"):
        reader = vtkJPEGReader()

    reader.SetFileName(fname)
    reader.Update()
    return reader.GetOutput()


def write_image(fname: str, image: vtkImageData):
    if fname.endswith("png"):
        writer = vtkPNGWriter()
    elif fname.endswith("jpg") or fname.endswith("jpeg"):
        writer = vtkJPEGWriter()
    elif fname.endswith("ps"):
        writer = vtkPostScriptWriter()
    else:
        logger.error(f"Unsupported file name {fname}")
        return

    writer.SetInputData(image)
    writer.SetFileName(fname)
    writer.Write()


def screenshot(renWin: vtkRenderWindow, fname: str = None):
    screenshot_impl = vtkWindowToImageFilter()
    screenshot_impl.SetInput(renWin)
    screenshot_impl.Modified()

    if fname is None:
        fname = f"ScreenshotIplotVTK-{datetime.datetime.isoformat(datetime.datetime.now())}.png"

    screenshot_impl.Update()
    write_image(fname, screenshot_impl.GetOutput())


def compare_images(valid: vtkImageData, test: vtkImageData) -> Tuple[float, Any]:
    comparator = vtkImageDifference()
    comparator.SetInputData(test)
    comparator.SetImageData(valid)
    comparator.Update()
    return comparator.GetThresholdedError(), comparator.GetOutput()


def regression_test(valid_image_abs_path: str, renWin: vtkRenderWindow, threshold=0.15) -> bool:
    valid_image_name = os.path.basename(valid_image_abs_path)
    test_image_name = valid_image_name.replace("valid", "test")
    diff_image_name = valid_image_name.replace("valid", "diff")

    baseline_dir = os.path.dirname(valid_image_abs_path)
    tests_dir = os.path.dirname(baseline_dir)

    test_image_path = os.path.join(tests_dir, test_image_name)
    diff_image_path = os.path.join(tests_dir, diff_image_name)

    screenshot(renWin, fname=test_image_path)

    if not os.path.exists(valid_image_abs_path):
        logger.warning(f"Valid image does not exist. Creating {valid_image_abs_path}")
        shutil.move(test_image_path, valid_image_abs_path)
        return False

    error, diff = compare_images(read_image(valid_image_abs_path), read_image(test_image_path))

    if error > threshold:
        write_image(diff_image_path, diff)
        return False
    else:
        os.remove(test_image_path)
        return True


def step_function(i: int, xs, ys, step_type: str):
    """See [steps-demo](https://matplotlib.org/stable/gallery/lines_bars_and_markers/step_demo.html)
    for meaning of step_type

    Args:
        i (int): an index into xs, ys
        xs (sequence): array of x values
        ys (sequence): array of y values
        step_type (str): step type- valid args are steps/steps-pre, steps-mid, steps-post

    Returns:
        np.ndarray: a new point either pre, mid or post
    """
    x, y = xs[i], ys[i]
    xp, yp = xs[i + 1], ys[i + 1]
    xmid = (x + xp) * 0.5
    if step_type == "steps-pre" or step_type == "steps":
        return np.array([[x, yp]])
    elif step_type == "steps-mid":
        return np.array([[xmid, y], [xmid, yp]])
    elif step_type == "steps-post":
        return np.array([[xp, y]])
