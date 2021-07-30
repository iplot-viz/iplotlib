import datetime
import numpy as np
import os
import shutil

from vtkmodules.vtkCommonDataModel import vtkImageData
from vtkmodules.vtkImagingCore import vtkImageDifference
from vtkmodules.vtkIOImage import vtkPNGReader, vtkJPEGReader, vtkPNGWriter, vtkJPEGWriter, vtkPostScriptWriter
from vtkmodules.vtkRenderingCore import vtkRenderWindow, vtkWindowToImageFilter

import logging
logger = logging.getLogger(__name__)

def read_image(fname: str) -> vtkImageData:

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


def compare_images(valid: vtkImageData, test: vtkImageData) -> float:
    comparator = vtkImageDifference()
    comparator.SetInputData(test)
    comparator.SetImageData(valid)
    comparator.Update()
    return comparator.GetThresholdedError(), comparator.GetOutput()


def regression_test(test_src: str, renWin: vtkRenderWindow) -> bool:
    test_fname = os.path.basename(test_src)
    dirname = os.path.dirname(test_src)
    baseline_dir = os.path.join(dirname, "baseline")

    image_fname = test_fname.replace(".py", ".png")
    valid_image_name = os.path.join(
        baseline_dir, image_fname.replace("test", "valid"))
    test_image_name = os.path.join(dirname, image_fname)
    diff_image_name = os.path.join(dirname, image_fname.replace("test", "diff"))

    screenshot(renWin, fname=test_image_name)

    if not os.path.exists(valid_image_name):
        logger.warning(f"Valid image does not exist. Creating {valid_image_name}")
        shutil.move(test_image_name, valid_image_name)
        return False

    error, diff = compare_images(read_image(
        valid_image_name), read_image(test_image_name))

    if error > 0.15:
        write_image(diff_image_name, diff)
        return False
    else:
        os.remove(test_image_name)
        return True


def step_function(i, xs, ys, step_type):
    x, y = xs[i], ys[i]
    xp, yp = xs[i + 1], ys[i + 1]
    xmid = (x + xp) * 0.5
    if step_type == "steps-pre" or step_type == "steps":
        return np.array([[x, yp]])
    elif step_type == "steps-mid":
        return np.array([[xmid, y], [xmid, yp]])
    elif step_type == "steps-post":
        return np.array([[xp, y]])
