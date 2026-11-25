"""Working the legend with the mouse, in both backends.

A click on a signal name hides the signal, as a click on its line does, while a
drag that starts anywhere on the legend, a name included, only moves it. Its left
and right sides resize it: narrower, the names are cut in the middle instead of
shrinking the font. The eye in the top right corner of the plot folds it away; the
legend keeps clear of the eye. All of it is kept in the canvas, so a redraw and the
workspace keep it too.
"""

import io
import os
import tempfile
import unittest
from unittest import mock

import numpy as np
import shiboken6
from matplotlib.backend_bases import MouseButton, MouseEvent
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser, _Legend
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
NAMES = ['EC-GN-P5C:R_T2_USC_AI_0_MHVPS_Voltage', 'EC-GN-P5C:R_T3_DBG_AO_1_BPS1_Feedback',
         'EC-GN-P5C:P_T4_WMAi2_EXP_BPS2_Expected', 'EC-GN-P5C:R_T2_USC_AI_1_BPS1_Voltage']
FONT_SIZE = 12


def _picture(path):
    """The pixels of a saved image; an SVG is drawn as QtSvg draws it."""
    if not path.endswith('.svg'):
        with Image.open(path) as image:
            return np.asarray(image.convert('RGB'), dtype=int)
    renderer = QSvgRenderer(path)
    image = QImage(renderer.defaultSize(), QImage.Format.Format_RGBA8888)
    image.fill(QColor('white'))
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    rows = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
    return rows[:, :image.width() * 4].reshape(image.height(), image.width(), 4)[..., :3].astype(int)


class _MatplotlibMouse:
    """Mouse gestures on a matplotlib legend, through the events of its figure.
    Points are in figure pixels, y up."""

    def __init__(self, qt_canvas, app):
        self.qt_canvas, self.app = qt_canvas, app
        self.parser = qt_canvas._parser

    def _event(self, kind, xy):
        renderer = self.qt_canvas._mpl_renderer
        renderer.callbacks.process(kind, MouseEvent(kind, renderer, xy[0], xy[1], button=MouseButton.LEFT))
        self.app.processEvents()

    def click(self, xy):
        self._event('button_press_event', xy)
        self._event('button_release_event', xy)
        self.qt_canvas._mpl_renderer.draw()

    def drag(self, start, dx, dy):
        """Drag from `start` by (dx, dy) pixels, right and down."""
        self._event('button_press_event', start)
        for k in range(1, 7):
            self._event('motion_notify_event', (start[0] + dx * k / 6, start[1] - dy * k / 6))
        self._event('button_release_event', (start[0] + dx, start[1] - dy))
        self.qt_canvas._mpl_renderer.draw()

    def name(self, impl, index):
        box = impl.get_legend().get_texts()[index].get_window_extent()
        return (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2

    def eye_button(self, impl):
        return self.parser._legend_eyes[impl]

    def eye(self, impl):
        box = self.eye_button(impl).get_window_extent()
        return (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2

    def spot(self, impl, horizontal, vertical):
        """A point of the legend: 'left', 'middle' or 'right'; 'top', 'middle' or 'bottom'.
        The sides are taken just inside the frame."""
        box = impl.get_legend().get_window_extent()
        x = {'left': box.x0 + 2, 'middle': (box.x0 + box.x1) / 2, 'right': box.x1 - 2}[horizontal]
        y = {'top': box.y1 - 2, 'middle': (box.y0 + box.y1) / 2, 'bottom': box.y0 + 2}[vertical]
        return x, y

    def box(self, impl):
        """Legend left, right and top as fractions of the plot area, from the left and the top."""
        box = self.parser.legend_box(impl)
        return box.x0, box.x1, 1 - box.y1

    def pixels(self, impl, eye=False):
        """Left, top, right and bottom of the legend (or of its eye button) in pixels,
        from the left and the top of the plot area."""
        box = (self.eye_button(impl) if eye else impl.get_legend()).get_window_extent()
        area = impl.get_window_extent()
        return box.x0 - area.x0, area.y1 - box.y1, box.x1 - area.x0, area.y1 - box.y0

    def area(self, impl):
        area = impl.get_window_extent()
        return area.width, area.height

    def names(self, impl):
        return [(text.get_text(), text.get_fontsize()) for text in impl.get_legend().get_texts()]

    def shown(self, impl):
        return impl.get_legend().get_visible()


class _PyQtGraphMouse:
    """Mouse gestures on a pyqtgraph legend, as real Qt mouse events on the view, so
    that pyqtgraph itself tells clicks from drags. Points are in scene pixels, y down."""

    def __init__(self, qt_canvas, app):
        self.qt_canvas, self.app = qt_canvas, app
        self.parser = qt_canvas._parser
        self.view = qt_canvas._parser.figure

    def _send(self, kind, xy, buttons):
        viewport = self.view.viewport()
        pos = QPointF(self.view.mapFromScene(QPointF(*xy)))
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        QApplication.sendEvent(viewport, QMouseEvent(kind, pos, QPointF(viewport.mapToGlobal(pos.toPoint())),
                                                     button, buttons, Qt.KeyboardModifier.NoModifier))
        self.app.processEvents()

    def click(self, xy):
        self._send(QEvent.Type.MouseButtonPress, xy, Qt.MouseButton.LeftButton)
        self._send(QEvent.Type.MouseButtonRelease, xy, Qt.MouseButton.NoButton)

    def drag(self, start, dx, dy):
        self._send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
        for k in range(1, 7):
            QTest.qWait(20)  # pyqtgraph drops the moves closer than 10 ms
            self._send(QEvent.Type.MouseMove, (start[0] + dx * k / 6, start[1] + dy * k / 6),
                       Qt.MouseButton.LeftButton)
        self._send(QEvent.Type.MouseButtonRelease, (start[0] + dx, start[1] + dy), Qt.MouseButton.NoButton)

    @staticmethod
    def _centre(item):
        centre = item.mapToScene(item.boundingRect().center())
        return centre.x(), centre.y()

    def name(self, impl, index):
        return self._centre(impl.legend.items[index][1])

    @staticmethod
    def eye_button(impl):
        return impl.legend.eye

    def eye(self, impl):
        return self._centre(self.eye_button(impl))

    def spot(self, impl, horizontal, vertical):
        legend = impl.legend
        x = {'left': 2, 'middle': legend.width() / 2, 'right': legend.width() - 2}[horizontal]
        y = {'top': 2, 'middle': legend.height() / 2, 'bottom': legend.height() - 2}[vertical]
        point = legend.mapToScene(QPointF(x, y))
        return point.x(), point.y()

    def box(self, impl):
        legend, vb = impl.legend, impl.getViewBox()
        top_left = legend.mapToItem(vb, QPointF(0, 0))
        return (top_left.x() / vb.width(), (top_left.x() + legend.width()) / vb.width(),
                top_left.y() / vb.height())

    def pixels(self, impl, eye=False):
        item = self.eye_button(impl) if eye else impl.legend
        box = item.mapRectToItem(impl.getViewBox(), item.rect() if eye else item.boundingRect())
        return box.left(), box.top(), box.right(), box.bottom()

    def area(self, impl):
        vb = impl.getViewBox()
        return vb.width(), vb.height()

    def names(self, impl):
        return [(label.text, float(label.opts['size'].replace('pt', ''))) for _, label in impl.legend.items]

    def shown(self, impl):
        return impl.legend.isVisible()


class LegendInteractionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapp()

    @staticmethod
    def _canvas(plot=None, names=NAMES):
        canvas = Canvas(1, 1, legend=True)
        canvas.font_size = FONT_SIZE
        plot = plot or PlotXY()
        x = np.linspace(0, 10, 100)
        for k, name in enumerate(names):
            signal = SignalXY(label=name, uid=f'uid-{k}')
            signal.set_data([x, np.sin(x) + k])
            plot.add_signal(signal)
        canvas.add_plot(plot, 0)
        return canvas, plot

    def _draw(self, backend, plot=None, mode=None, names=NAMES):
        canvas, plot = self._canvas(plot, names)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(900, 600)
        qt_canvas.show()
        self.app.processEvents()
        if mode is not None:
            qt_canvas.set_mouse_mode(mode)
        if backend == 'matplotlib':
            qt_canvas._mpl_renderer.draw()
        self.addCleanup(qt_canvas.close)
        mouse = (_MatplotlibMouse if backend == 'matplotlib' else _PyQtGraphMouse)(qt_canvas, self.app)
        return qt_canvas, plot, mouse

    def _redraw(self, qt_canvas):
        qt_canvas.refresh()
        self.app.processEvents()
        if hasattr(qt_canvas, '_mpl_renderer'):
            qt_canvas._mpl_renderer.draw()

    @staticmethod
    def _impl(qt_canvas):
        return qt_canvas._parser._signal_impl_plot_lut['uid-0']

    @staticmethod
    def _shown(plot):
        """Whether each signal is drawn, as its first line says, and as the canvas keeps it."""
        lines = [s.lines[0] for s in plot.signals[1]]
        return ([line.get_visible() if hasattr(line, 'get_visible') else line.isVisible() for line in lines],
                [not s.hidden for s in plot.signals[1]])

    def test_a_click_on_a_name_hides_its_signal_until_clicked_again(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend)

                mouse.click(mouse.name(self._impl(qt_canvas), 1))
                self.assertEqual(self._shown(plot), ([True, False, True, True], [True, False, True, True]))

                self._redraw(qt_canvas)
                self.assertEqual(self._shown(plot), ([True, False, True, True], [True, False, True, True]))

                mouse.click(mouse.name(self._impl(qt_canvas), 1))
                self.assertEqual(self._shown(plot), ([True] * 4, [True] * 4))

    def test_a_drag_from_a_name_moves_the_legend_and_hides_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend)
                left, _, top = mouse.box(self._impl(qt_canvas))

                mouse.drag(mouse.name(self._impl(qt_canvas), 2), -250, 120)

                moved = mouse.box(self._impl(qt_canvas))
                self.assertLess(moved[0], left - 0.1)
                self.assertGreater(moved[2], top + 0.1)
                self.assertEqual(self._shown(plot), ([True] * 4, [True] * 4))

    def test_a_dragged_legend_keeps_its_place_after_a_redraw(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend)
                mouse.drag(mouse.spot(self._impl(qt_canvas), 'middle', 'bottom'), -200, 150)
                moved = mouse.box(self._impl(qt_canvas))

                self._redraw(qt_canvas)

                np.testing.assert_allclose(mouse.box(self._impl(qt_canvas)), moved, atol=0.005)
                np.testing.assert_allclose(plot.legend_anchor['1'], [moved[0], moved[2]], atol=0.005)

    def test_the_legend_takes_its_clicks_over_the_curves_in_every_mode(self):
        # Over a curve, a press could start a shift or a ruler instead.
        for backend in BACKENDS:
            for mode in (Canvas.MOUSE_MODE_SELECT, Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_RULER):
                with self.subTest(backend=backend, mode=mode):
                    plot = PlotXY(legend_anchor={'1': [0.3, 0.3]})
                    qt_canvas, plot, mouse = self._draw(backend, plot, mode)
                    impl = self._impl(qt_canvas)
                    limits = qt_canvas._parser.get_oaw_axis_limits(impl, 0)

                    mouse.click(mouse.name(impl, 3))
                    mouse.click(mouse.eye(impl))

                    self.assertEqual(self._shown(plot)[1], [True, True, True, False])
                    self.assertFalse(mouse.shown(self._impl(qt_canvas)))
                    self.assertEqual(qt_canvas._parser.get_oaw_axis_limits(impl, 0), limits)

    def test_the_eye_folds_the_legend_away_and_back(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend)
                eye = mouse.eye(self._impl(qt_canvas))

                mouse.click(eye)
                self.assertFalse(mouse.shown(self._impl(qt_canvas)))
                self._redraw(qt_canvas)
                self.assertFalse(mouse.shown(self._impl(qt_canvas)))
                # Folded, the eye stays where it was, to unfold the legend.
                np.testing.assert_allclose(mouse.eye(self._impl(qt_canvas)), eye, atol=2)

                mouse.click(mouse.eye(self._impl(qt_canvas)))
                self.assertTrue(mouse.shown(self._impl(qt_canvas)))
                self.assertFalse(plot.legend_collapsed)

    def test_the_eye_leaves_the_legend_box_as_it_was_drawn_without_it(self):
        # Same size; a legend in the top right corner only moves aside for the eye.
        for backend, owner, method in (('matplotlib', MatplotlibParser, '_add_legend_eye'), ('pyqt', _Legend, 'add_eye')):
            for position in ('upper right', 'lower left'):
                with self.subTest(backend=backend, position=position):
                    qt_canvas, _, mouse = self._draw(backend, PlotXY(legend_position=position))
                    with_eye = mouse.pixels(self._impl(qt_canvas))
                    with mock.patch.object(owner, method, lambda *args: None):
                        qt_canvas, _, mouse = self._draw(backend, PlotXY(legend_position=position))
                        without_eye = mouse.pixels(self._impl(qt_canvas))
                    left, top, right, bottom = with_eye
                    left_alone, top_alone, right_alone, bottom_alone = without_eye
                    self.assertAlmostEqual(right - left, right_alone - left_alone, delta=0.5)
                    self.assertAlmostEqual(bottom - top, bottom_alone - top_alone, delta=0.5)
                    if position == 'lower left':
                        np.testing.assert_allclose(with_eye, without_eye, atol=0.5)

    def _assert_clear(self, mouse, impl):
        left, top, right, bottom = mouse.pixels(impl)
        eye_left, eye_top, eye_right, eye_bottom = mouse.pixels(impl, eye=True)
        self.assertTrue(right < eye_left or top > eye_bottom,
                        f"legend {(left, top, right, bottom)} over the eye {(eye_left, eye_top, eye_right, eye_bottom)}")

    def test_the_eye_is_in_the_top_right_corner_and_the_legend_keeps_clear_of_it(self):
        for backend in BACKENDS:
            for position in ('upper right', 'upper left', 'upper center', 'center right', 'lower right'):
                with self.subTest(backend=backend, position=position):
                    qt_canvas, _, mouse = self._draw(backend, PlotXY(legend_position=position))
                    impl = self._impl(qt_canvas)
                    width, _ = mouse.area(impl)
                    eye_left, eye_top, eye_right, _ = mouse.pixels(impl, eye=True)
                    self.assertAlmostEqual(width - eye_right, eye_top, delta=1)
                    self.assertLess(eye_top, 8)
                    self._assert_clear(mouse, impl)
                    if position == 'upper right':
                        # Next to it, at the same height.
                        left, top, right, _ = mouse.pixels(impl)
                        self.assertTrue(0 < eye_left - right <= 4, f"{eye_left - right} px from the eye")
                        self.assertAlmostEqual(top, eye_top, delta=1)

    def test_a_legend_dragged_over_the_eye_keeps_clear_of_it(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, mouse = self._draw(backend, PlotXY(legend_anchor={'1': [0.2, 0.3]}), names=NAMES[:2])

                mouse.drag(mouse.name(self._impl(qt_canvas), 0), 2000, -400)

                self._assert_clear(mouse, self._impl(qt_canvas))

    def test_a_legend_dragged_to_the_right_keeps_clear_of_the_eye_when_the_window_narrows(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, mouse = self._draw(backend, names=NAMES[:2])
                mouse.drag(mouse.name(self._impl(qt_canvas), 0), 2000, -400)

                qt_canvas.resize(600, 600)
                self.app.processEvents()
                if backend == 'matplotlib':
                    qt_canvas._mpl_renderer.draw()
                    self.app.processEvents()
                    qt_canvas._mpl_renderer.draw()

                self._assert_clear(mouse, self._impl(qt_canvas))

    def test_the_eye_stays_in_its_corner_while_the_legend_is_folded(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, mouse = self._draw(backend, PlotXY(legend_anchor={'1': [0.3, 0.4]}))
                corner = mouse.pixels(self._impl(qt_canvas), eye=True)

                mouse.click(mouse.eye(self._impl(qt_canvas)))
                self._redraw(qt_canvas)

                np.testing.assert_allclose(mouse.pixels(self._impl(qt_canvas), eye=True), corner, atol=1)

    def test_a_matplotlib_drag_draws_the_figure_once_not_on_every_move(self):
        qt_canvas, _, mouse = self._draw('matplotlib', PlotXY(legend_anchor={'1': [0.3, 0.2]}))
        renderer = qt_canvas._mpl_renderer
        start = mouse.spot(self._impl(qt_canvas), 'right', 'middle')
        draws = []
        draw = renderer.draw
        with mock.patch.object(renderer, 'draw', lambda: (draws.append(1), draw())):
            mouse._event('button_press_event', start)
            for k in range(1, 13):
                mouse._event('motion_notify_event', (start[0] - 10 * k, start[1]))
            moves_drawn = len(draws)
            mouse._event('button_release_event', (start[0] - 120, start[1]))
        self.assertEqual(moves_drawn, 1)
        self.assertIn('…', mouse.names(self._impl(qt_canvas))[0][0])

    def test_a_drag_from_the_eye_moves_nothing_and_folds_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend)
                impl = self._impl(qt_canvas)
                box, eye = mouse.box(impl), mouse.eye(impl)
                limits = qt_canvas._parser.get_oaw_axis_limits(impl, 0)

                mouse.drag(eye, -150, 80)

                np.testing.assert_allclose(mouse.box(self._impl(qt_canvas)), box, atol=1e-6)
                self.assertTrue(mouse.shown(self._impl(qt_canvas)))
                self.assertIsNone(plot.legend_anchor)
                self.assertEqual(qt_canvas._parser.get_oaw_axis_limits(impl, 0), limits)

    def test_saved_images_leave_the_eye_out(self):
        """In every format the screenshot button offers."""
        for backend in BACKENDS:
            for ext in ('png', 'jpg', 'svg'):
                with self.subTest(backend=backend, format=ext):
                    qt_canvas, _, mouse = self._draw(backend)
                    eye = mouse.eye_button(self._impl(qt_canvas))
                    folder = tempfile.TemporaryDirectory()
                    self.addCleanup(folder.cleanup)
                    path = os.path.join(folder.name, f'canvas.{ext}')

                    qt_canvas.save_canvas_image(path)
                    saved = _picture(path)
                    self.assertTrue(eye.get_visible() if backend == 'matplotlib' else eye.isVisible())

                    # The same picture with the eye hidden by hand.
                    if backend == 'matplotlib':
                        eye.set_visible(False)
                        qt_canvas._mpl_renderer.draw()
                    else:
                        eye.hide()
                    qt_canvas.save_canvas_image(path)
                    without_eye = _picture(path)
                    self.assertEqual(saved.shape, without_eye.shape)
                    self.assertEqual(np.abs(saved - without_eye).max(), 0)

    def test_an_image_exported_without_the_qt_canvas_has_no_eye(self):
        """As the command line exports one: no eye to leave out, so the legend keeps its
        place, and a folded legend stays folded."""
        for backend, parser_class in (('matplotlib', MatplotlibParser), ('pyqt', PyQtGraphParser)):
            for folded in (False, True):
                with self.subTest(backend=backend, folded=folded):
                    canvas, plot = self._canvas()
                    plot.legend_collapsed = ['1'] if folded else None
                    parser = parser_class()
                    folder = tempfile.TemporaryDirectory()
                    self.addCleanup(folder.cleanup)
                    if backend == 'pyqt':
                        # Deleted here rather than at exit, when Python has already torn
                        # down its items while Qt still asks them for their size.
                        self.addCleanup(shiboken6.delete, parser.figure)

                    parser.export_image(os.path.join(folder.name, 'canvas.png'), canvas=canvas,
                                        dpi=100, width=1920, height=1080)

                    impl = parser._signal_impl_plot_lut['uid-0']
                    if backend == 'matplotlib':
                        self.assertEqual(parser._legend_eyes, {})
                        self.assertEqual(impl.get_legend().get_visible(), not folded)
                    else:
                        self.assertIsNone(impl.legend.eye)
                        self.assertEqual(impl.legend.isVisible(), not folded)

    def test_matplotlib_files_leave_the_eye_out(self):
        qt_canvas, _, _ = self._draw('matplotlib')
        figure = qt_canvas._parser.figure
        eye = qt_canvas._parser._legend_eyes[self._impl(qt_canvas)]

        def png():
            buffer = io.BytesIO()
            figure.savefig(buffer, format='png')
            return np.asarray(Image.open(buffer).convert('RGB'), dtype=int)

        saved = png()
        eye.set_visible(False)
        self.assertEqual(np.abs(saved - png()).max(), 0)

    def test_a_narrower_legend_cuts_the_names_in_the_middle_and_keeps_the_font(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend, PlotXY(legend_anchor={'1': [0.3, 0.2]}))

                mouse.drag(mouse.spot(self._impl(qt_canvas), 'right', 'middle'), -150, 0)

                names = mouse.names(self._impl(qt_canvas))
                for (shown, size), full in zip(names, NAMES):
                    self.assertIn('…', shown)
                    head, tail = shown.split('…')
                    self.assertTrue(full.startswith(head) and full.endswith(tail), shown)
                    self.assertEqual(size, FONT_SIZE)
                self.assertGreater(plot.legend_width, 0)

                self._redraw(qt_canvas)
                self.assertEqual(mouse.names(self._impl(qt_canvas)), names)

    def test_the_star_of_a_downsampled_signal_goes_with_its_whole_name(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend, PlotXY(legend_anchor={'1': [0.1, 0.1]}, legend_width=20))
                signal = plot.signals[1][0]
                for downsampled, width in ((True, 1000), (False, 900)):
                    signal.isDownsampled = downsampled
                    qt_canvas._parser.legend_downsampled_signal(signal, self._impl(qt_canvas), signal.lines[0])
                    # A new window width cuts the names again, from their whole names.
                    qt_canvas.resize(width, 600)
                    self.app.processEvents()
                    if backend == 'matplotlib':
                        qt_canvas._mpl_renderer.draw()

                    shown = mouse.names(self._impl(qt_canvas))[0][0]
                    self.assertIn('…', shown)
                    self.assertEqual(shown.endswith('*'), downsampled, shown)

    def test_resizing_from_the_left_keeps_the_right_side(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend, PlotXY(legend_anchor={'1': [0.3, 0.2]}))
                left, right, _ = mouse.box(self._impl(qt_canvas))

                mouse.drag(mouse.spot(self._impl(qt_canvas), 'left', 'middle'), 120, 0)

                new_left, new_right, _ = mouse.box(self._impl(qt_canvas))
                self.assertGreater(new_left, left + 0.05)
                self.assertAlmostEqual(new_right, right, delta=0.005)

    def test_only_the_width_is_resized(self):
        # A corner resizes as its side does; the top and the bottom move the legend.
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, mouse = self._draw(backend, PlotXY(legend_anchor={'1': [0.3, 0.2]}))
                impl = self._impl(qt_canvas)
                left, top, right, bottom = mouse.pixels(impl)

                mouse.drag(mouse.spot(impl, 'right', 'bottom'), -100, -45)

                new_left, new_top, new_right, new_bottom = mouse.pixels(self._impl(qt_canvas))
                self.assertAlmostEqual(new_right, right - 100, delta=15)
                np.testing.assert_allclose((new_left, new_top, new_bottom), (left, top, bottom), atol=0.5)

                width = plot.legend_width
                mouse.drag(mouse.spot(self._impl(qt_canvas), 'middle', 'bottom'), 0, -45)

                moved_left, moved_top, moved_right, moved_bottom = mouse.pixels(self._impl(qt_canvas))
                self.assertEqual(plot.legend_width, width)
                self.assertAlmostEqual(moved_top, top - 45, delta=2)
                self.assertAlmostEqual(moved_bottom - moved_top, bottom - top, delta=0.5)

    def test_a_narrowed_legend_keeps_its_share_of_the_plot_width_when_the_window_changes(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = Canvas(1, 1, legend=True)
                canvas.font_size = FONT_SIZE
                plot = PlotXY(legend_anchor={'1': [0.05, 0.05]}, legend_width=30)
                x = np.linspace(0, 10, 100)
                for k, name in enumerate(NAMES):
                    signal = SignalXY(label=name, uid=f'uid-{k}')
                    signal.set_data([x, np.sin(x) + k])
                    plot.add_signal(signal)
                canvas.add_plot(plot, 0)
                # Drawn before the window has its size, as a canvas built in the background.
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                self.addCleanup(qt_canvas.close)
                mouse = (_MatplotlibMouse if backend == 'matplotlib' else _PyQtGraphMouse)(qt_canvas, self.app)
                for width in (900, 1400):
                    qt_canvas.resize(width, 600)
                    qt_canvas.show()
                    self.app.processEvents()
                    if backend == 'matplotlib':
                        qt_canvas._mpl_renderer.draw()
                    left, right, _ = mouse.box(self._impl(qt_canvas))
                    self.assertAlmostEqual(right - left, 0.30, delta=0.03, msg=f"window {width} px wide")

    def test_the_place_is_found_whether_the_stack_is_named_or_numbered(self):
        # Reading a workspace back can turn the stack names into numbers.
        for backend in BACKENDS:
            for stack in ('1', 1):
                with self.subTest(backend=backend, stack=type(stack).__name__):
                    qt_canvas, plot, mouse = self._draw(backend, PlotXY(legend_anchor={stack: [0.2, 0.3]}))
                    left, _, top = mouse.box(self._impl(qt_canvas))
                    self.assertAlmostEqual(left, 0.2, delta=0.005)
                    self.assertAlmostEqual(top, 0.3, delta=0.005)


if __name__ == '__main__':
    unittest.main()
