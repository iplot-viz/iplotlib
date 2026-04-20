# iplotlib test suite

## How to run

From the repository root:

```bash
pytest iplotlib/
```

On a headless environment (CI runners, remote servers):

```bash
xvfb-run pytest iplotlib/
```

Running a single test file:

```bash
pytest iplotlib/standalone/tests/test_rendering.py -v
```

## Layout

```
iplotlib/
├── core/tests/                  Pure-python unit tests (no Qt)
│   ├── test_01_property_manager.py
│   ├── test_03_canvas.py             Canvas shape, add_plot, mouse mode
│   ├── test_04_history_manager.py    Undo/redo stack (dummy command)
│   ├── test_05_axis.py               Axis / RangeAxis / LinearAxis
│   ├── test_06_plot.py               PlotXY / PlotContour / PlotImage
│   ├── test_07_signal.py             SignalXY / SignalContour
│   ├── test_08_canvas_focus.py       focus_plot, full_mode_all_stack
│   ├── test_09_workspace_roundtrip.py  to_dict / from_dict / to_json
│   ├── test_10_canvas_crosshair.py   Crosshair attribute state
│   └── test_11_canvas_legend.py      Legend attribute state
├── impl/matplotlib/tests/       Matplotlib-specific tests
├── impl/pyqtgraph/tests/        PyQtGraph-specific tests
├── impl/vtk/tests/              VTK tests (currently skipped)
├── interface/tests/             Regression tests for iplotSignalAdapter
│   └── test_truncate_to_target.py   Locks in the fixes from issue #69
├── qt/testing/                  Shared test helpers (see below)
└── standalone/tests/            Backend-agnostic integration tests
    ├── baseline/                Committed PNGs for visual regression
    ├── test_standalone.py       End-to-end: example canvas render
    ├── test_rendering.py        Parametrised render tests (both backends)
    ├── test_interactions.py     Pan/zoom with before/after image capture
    └── test_history_integration.py  IplotAxesRangeCmd + undo on real backend
```

## Shared helpers (`iplotlib.qt.testing`)

- `ensure_qapp()` — returns the singleton offscreen `QApplication`. Registers
  DejaVu Sans (reused from matplotlib's bundle) so offscreen Qt has real
  fonts on any platform. Without this, Windows offscreen renders all text as
  empty glyphs.
- `compare_pixmap_to_baseline(pixmap, path, tol=5.0)` — saves the pixmap as
  PNG and runs matplotlib's `compare_images` against `path`. If `path` does
  not exist yet, the current render is promoted to baseline and the test
  passes (bootstrap mode). Tolerance is the RMS threshold that absorbs
  anti-aliasing drift between platforms.
- `QAppTestAdapter` / `QAppOffscreenTestAdapter` — `unittest.TestCase`
  subclasses that set up the Qt application for you.

## Backend parametrisation

Rendering and interaction tests iterate over `BACKENDS = ('matplotlib', 'pyqt')`
using `self.subTest(backend=backend)` so the same scenario exercises both
backends and failures report per backend.

## Baselines

Baseline PNGs live under `iplotlib/standalone/tests/baseline/`. Each render
test is a visual regression: the produced image is diffed against the
committed baseline with an RMS tolerance of 5.0.

Adding a new rendering test:

1. Write the test using `self._render(backend, core_canvas, "name")`.
2. First run creates the baseline automatically.
3. Inspect the generated PNG visually.
4. Commit the baseline together with the test.

Regenerating a baseline after an intentional change:

1. Delete the relevant PNG under `baseline/`.
2. Run the test once — it will recreate the baseline.
3. Commit the updated baseline.

Mismatches leave a `*_actual.png` next to the baseline for side-by-side
comparison. On a clean pass the `*_actual.png` is removed automatically.

## Interactive tests

`standalone/tests/test_interactions.py` drives the backends through the public
axis APIs that the interactive modes call (`ViewBox.setRange` in pyqtgraph,
`Axes.set_xlim` in matplotlib). It also captures a before-and-after pixmap so
visual regressions of the rendering after a zoom/pan are caught too, not
just the numerical range change.

Full `QTest.mousePress`/`mouseMove`/`mouseRelease` sequences were tried but
are unreliable on the offscreen platform because hit-testing depends on
widget geometry that is never laid out on screen.

The crosshair rendering is bound to live mouse-motion events
(`motion_notify_event` in matplotlib, `sigMouseMoved` in pyqtgraph). Static
render tests of a canvas with `crosshair_enabled=True` therefore only verify
that the render path does not break — the crosshair glyph itself is not
drawn until a cursor moves over the canvas. Capturing the glyph drawn at a
specific cursor position would need a separate test that dispatches a
synthetic motion event to the backend-specific event system.

## Regression tests

- `interface/tests/test_truncate_to_target.py` — locks in the behaviour of
  the shape-alignment helper after the fixes from issue #69 (dtype
  preservation, empty-source silence, warning dedup, axis-label message).
- `core/tests/test_09_workspace_roundtrip.py` — `Canvas.to_dict` / `from_dict`
  and JSON variant, which is what MINT uses to persist workspaces; a silent
  break here loses user work on reload.

When fixing a new bug, add a regression test that would have caught it and
name it after the issue number in the docstring.
