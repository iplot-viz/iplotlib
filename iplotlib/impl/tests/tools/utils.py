# iplotlib/impl/tests/tools/utils.py

import os
import shutil

import numpy as np
from PIL import Image
from matplotlib.figure import Figure
import logging

logger = logging.getLogger(__name__)


def read_image(path: str) -> np.ndarray:
    """
    Read an image file into a numpy array (RGB).
    """
    img = Image.open(path).convert('RGB')
    return np.array(img)


def write_image(path: str, data: np.ndarray) -> None:
    """
    Write a numpy RGB array to an image file (PNG or JPEG).
    """
    img = Image.fromarray(data)
    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


def screenshot(obj, path: str) -> None:
    """
    Capture the canvas or Figure into an image file.
    - If obj has a `savefig` method, use it.
    - If obj is a Matplotlib Figure, call Figure.savefig().
    """
    # decide how to snapshot
    if hasattr(obj, 'savefig'):
        # e.g. FigureCanvas or parser with savefig-like API
        obj.savefig(path)
    elif isinstance(obj, Figure):
        obj.savefig(path)
    else:
        raise RuntimeError(f"Cannot screenshot object of type {type(obj)}")


def compare_images(valid: np.ndarray, test: np.ndarray) -> float:
    """
    Compute mean squared error between two RGB images.
    """
    if valid.shape != test.shape:
        raise ValueError("Image shapes differ: "
                         f"{valid.shape} vs {test.shape}")
    diff = (valid.astype(float) - test.astype(float)) ** 2
    return float(np.mean(diff))


def regression_test(valid_path: str,
                    screenshot_target,
                    threshold: float = 1.0) -> bool:
    """
    Compare a newly generated image against the baseline.
    If the baseline is missing, create it and fail the test.
    Returns True if within threshold MSE, False otherwise.
    """
    # derive test and diff names
    base_dir   = os.path.dirname(valid_path)
    name       = os.path.basename(valid_path)
    test_name  = name.replace('valid', 'test')
    diff_name  = name.replace('valid', 'diff')

    test_path  = os.path.join(base_dir, test_name)
    diff_path  = os.path.join(base_dir, diff_name)

    # generate test image
    screenshot(screenshot_target, test_path)

    # if no baseline, initialize it and fail
    if not os.path.exists(valid_path):
        logger.warning(f"Baseline missing, creating {valid_path}")
        shutil.move(test_path, valid_path)
        return False

    # load and compare
    valid_img = read_image(valid_path)
    test_img  = read_image(test_path)
    error     = compare_images(valid_img, test_img)

    if error > threshold:
        # save diff: absolute difference stretched to full range
        diff = np.abs(valid_img.astype(int) - test_img.astype(int)).astype(np.uint8)
        write_image(diff_path, diff)
        logger.error(f"Image regression failed: MSE={error:.2f}")
        return False
    else:
        # cleanup test image if close enough
        os.remove(test_path)
        return True
