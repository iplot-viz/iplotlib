"""Image comparison helper for visual regression tests.

Uses matplotlib's bundled image comparator (already a dependency) to produce a
pixel-level diff with tolerance. Baselines are persisted under the test folder
and checked into the repository; the first run auto-writes the baseline when
one is missing so a new test can bootstrap itself without a manual step.
"""

import os
import shutil

from matplotlib.testing.compare import compare_images


def compare_pixmap_to_baseline(pixmap, baseline_path: str, tol: float = 5.0) -> None:
    """Save ``pixmap`` to a temporary PNG next to ``baseline_path`` and diff it.

    If the baseline does not exist yet, the generated image is promoted to the
    baseline and the test passes (bootstrap mode).  Otherwise the images are
    compared pixel by pixel; ``tol`` is the RMS tolerance accepted by
    matplotlib's ``compare_images`` (default 5.0, generous enough to absorb
    anti-aliasing differences between platforms).
    """
    actual_path = baseline_path.replace('.png', '_actual.png')
    pixmap.save(actual_path, 'PNG')
    assert os.path.exists(actual_path), f"pixmap.save produced no file: {actual_path}"

    if not os.path.exists(baseline_path):
        shutil.copyfile(actual_path, baseline_path)
    else:
        diff = compare_images(baseline_path, actual_path, tol=tol)
        if diff is not None:
            raise AssertionError(
                f"Image mismatch vs baseline {os.path.basename(baseline_path)}: {diff}")

    # Clean up the actual image once the baseline is established or matches.
    try:
        os.remove(actual_path)
    except OSError:
        pass
