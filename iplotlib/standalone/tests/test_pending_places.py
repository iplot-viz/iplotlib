"""A canvas drawn with some of its places pending shows there that their data are read, and draws each of their
plots on its own once those data are, as the canvas drawn whole draws it."""

import random
import time
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.impl_base import PENDING_PLACE_TEXT, PENDING_PROGRESS_TEXT, BackendParserBase
from iplotlib.core.plot import PlotXY, PlotXYWithSlider
from iplotlib.core.ruler import Ruler
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.qt import QtMatplotlibCanvas
from iplotlib.impl.matplotlib.qt.qtMatplotlibCanvas import PROGRESS_RENDER_S
from iplotlib.interface.iplotSignalAdapter import AccessHelper, ParserHelper
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

T0 = 1_788_873_880_000_000_000
HOUR = 3600 * 10**9
BACKENDS = ('matplotlib', 'pyqt')


class _DataAccess:
    """A ramp per variable, of a height that tells which variable it is."""

    def get_data(self, data_s_name, **kwargs):
        x = np.linspace(kwargs['tsS'], kwargs['tsE'], 40).astype(np.int64)
        y = np.linspace(0.0, 1.0, 40) * len(kwargs['varname'])
        return SimpleNamespace(errcode=0, errdesc='', xdata=x, ydata=y, xunit='ns', yunit='A', resolved_pulse=None)

    def get_data_source(self, name):
        return None


def _variable(name):
    return SignalXY(name=name, label=name, data_source='uda', ts_start=T0, ts_end=T0 + HOUR)


def _canvas() -> Canvas:
    """Two columns: two plots, the lower one with two stacks, beside a plot as tall as both."""
    canvas = Canvas(2, 2, title="pending places")
    for col, plots in enumerate([[['A'], ['BB', 'CCC']], [['DDDD']]]):
        for row, stacks in enumerate(plots):
            plot = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis() for _ in stacks]], row_span=2 if col else 1)
            for stack, name in enumerate(stacks, start=1):
                plot.add_signal(_variable(name), stack=stack)
            canvas.add_plot(plot, col)
    return canvas


def _shared_pair() -> Canvas:
    """Two plots of the same time range, one above the other, that share their time axis."""
    canvas = Canvas(2, 1)
    for name in ('A', 'BB'):
        plot = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis()]])
        plot.add_signal(_variable(name), stack=1)
        canvas.add_plot(plot, 0)
    canvas.shared_x_axis = True
    return canvas


def _slider_pair() -> Canvas:
    """Two plots with a slider over the same frames, which move together."""
    canvas = Canvas(2, 1)
    frames = (T0 + np.arange(40) * 10**9).astype(np.int64)
    for k in range(2):
        x_axis = LinearAxis(is_date=True)
        x_axis.original_begin, x_axis.original_end = x_axis.begin, x_axis.end = int(frames[0]), int(frames[-1])
        plot = PlotXYWithSlider(axes=[x_axis, [LinearAxis()]])
        signal = SignalXY(label=f"s{k}")
        signal.set_data([frames, np.outer(np.arange(40, dtype=float), np.ones(40)) + k, frames])
        plot.add_signal(signal, stack=1)
        canvas.add_plot(plot, 0)
    canvas.shared_x_axis = True
    return canvas


def _set_time_range(plot, window):
    """Give the plot and its signals a time range of their own, as a table row with one does."""
    x_axis = plot.axes[0]
    x_axis.original_begin, x_axis.original_end = x_axis.begin, x_axis.end = window
    for stack in plot.signals.values():
        for signal in stack:
            signal.ts_start, signal.ts_end = window


def _places(canvas: Canvas) -> dict:
    return {(i, j): (plot.row_span, plot.col_span)
            for i, column in enumerate(canvas.plots) for j, plot in enumerate(column) if plot is not None}


class PendingPlacesTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        ParserHelper.env.clear()
        self.addCleanup(ParserHelper.env.clear)
        for name in ('da', 'pool'):
            self.addCleanup(setattr, AccessHelper, name, getattr(AccessHelper, name))
        AccessHelper.da = _DataAccess()
        AccessHelper.pool = None

    def _qt_canvas(self, backend, canvas: Canvas, pending: dict = None):
        qt_canvas = IplotQtCanvasFactory.new(backend)
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.resize(1200, 800)
        if pending is not None:
            qt_canvas.set_pending_places(canvas, pending)
        qt_canvas.set_canvas(canvas)
        self.app.processEvents()
        return qt_canvas

    @staticmethod
    def _drawn(qt_canvas) -> list:
        """What the canvas shows of each plot, in the order of the plots: per stack, its X and Y ranges and the data
        of its lines."""
        parser = qt_canvas._parser
        drawn = []
        for column in parser.canvas.plots:
            for plot in column:
                stacks = []
                for impl in parser._plot_impl_plot_lut.get(id(plot), []) if plot is not None else []:
                    lines, _, _ = parser.get_impl_lines(impl)
                    data = [tuple(np.round(np.asarray(values, dtype=float), 6).tolist()
                                  for values in parser.get_impl_data(line)) for line in lines]
                    stacks.append((tuple(np.round(parser.get_oaw_axis_limits(impl, 0), 3)),
                                   tuple(np.round(parser.get_oaw_axis_limits(impl, 1), 6)), sorted(data)))
                drawn.append(stacks)
        return drawn

    @staticmethod
    def _shown(qt_canvas, plot) -> bool:
        """Whether the canvas shows the plot: its implementation plots are in the figure."""
        parser = qt_canvas._parser
        impls = parser._plot_impl_plot_lut.get(id(plot), [])
        try:
            if isinstance(qt_canvas, QtMatplotlibCanvas):
                return bool(impls) and all(impl in parser.figure.axes for impl in impls)
            return bool(impls) and all(impl.scene() is not None for impl in impls)
        except RuntimeError:
            # Deleted with the Qt item that held it.
            return False

    @staticmethod
    def _x_window(qt_canvas, plot) -> tuple:
        parser = qt_canvas._parser
        impl = parser._plot_impl_plot_lut[id(plot)][0]
        return tuple(round(float(value) / 1e9, 3) for value in parser.get_oaw_axis_limits(impl, 0))

    @staticmethod
    def _zoom(qt_canvas, plot):
        """Narrow the X window of the plot to its middle third, as a zoom gesture does."""
        parser = qt_canvas._parser
        impl = parser._plot_impl_plot_lut[id(plot)][0]
        begin, end = parser.get_oaw_axis_limits(impl, 0)
        parser.set_oaw_axis_limits(impl, 0, (begin + (end - begin) / 3, end - (end - begin) / 3))

    @staticmethod
    def _pending_shown(qt_canvas) -> set:
        """The places that show that their data are read."""
        parser = qt_canvas._parser
        if hasattr(parser, '_pending_texts'):
            return {place for place, text in parser._pending_texts.items() if text.get_text() == PENDING_PLACE_TEXT}
        return {(col, row) for (row, col), cell in parser._cell_gl.items()
                if any(getattr(item, 'text', None) == PENDING_PLACE_TEXT for item in cell.items)}

    def test_each_plot_drawn_on_its_own_is_drawn_as_the_canvas_drawn_whole_draws_it(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                whole = self._drawn(self._qt_canvas(backend, _canvas()))
                canvas = _canvas()
                places = _places(canvas)
                qt_canvas = self._qt_canvas(backend, canvas, places)
                plots = [plot for column in canvas.plots for plot in column]

                pending = self._pending_shown(qt_canvas)
                nothing = self._drawn(qt_canvas)
                for plot in random.Random(7).sample(plots, len(plots)):
                    self.assertTrue(qt_canvas.draw_plot(plot))
                self.app.processEvents()

                self.assertEqual(pending, set(places))
                self.assertEqual(nothing, [[], [], []])
                self.assertEqual(self._pending_shown(qt_canvas), set())
                self.assertEqual(qt_canvas._parser.pending_places, {})
                self.assertEqual(self._drawn(qt_canvas), whole)

    def test_a_place_says_how_many_of_the_data_of_its_plot_are_read(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))

                qt_canvas.show_pending_progress(0, 1, 1, 2)
                self.app.processEvents()
                told = self._pending_texts(qt_canvas)
                qt_canvas.draw_plot(canvas.plots[0][1])

                self.assertEqual(told, {(0, 0): PENDING_PLACE_TEXT, (0, 1): PENDING_PROGRESS_TEXT.format(1, 2),
                                        (1, 0): PENDING_PLACE_TEXT})
                self.assertEqual(PENDING_PROGRESS_TEXT.format(1, 2), "Retrieving data (1/2) ..")
                self.assertEqual(set(self._pending_texts(qt_canvas)), {(0, 0), (1, 0)})

    def test_the_progress_of_a_place_no_longer_pending_changes_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                qt_canvas.draw_plot(canvas.plots[0][1])

                qt_canvas.show_pending_progress(0, 1, 1, 2)

                self.assertEqual(self._pending_texts(qt_canvas), {(0, 0): PENDING_PLACE_TEXT,
                                                                  (1, 0): PENDING_PLACE_TEXT})

    def test_the_progress_of_a_place_renders_the_figure_only_when_a_render_takes_little(self):
        canvas = _canvas()
        qt_canvas = self._qt_canvas('matplotlib', canvas, _places(canvas))
        renders = []
        for took in (PROGRESS_RENDER_S / 2, PROGRESS_RENDER_S * 4):
            qt_canvas._render_timer.stop()
            qt_canvas._render_took = took

            qt_canvas.show_pending_progress(0, 1, 1, 2)

            renders.append(qt_canvas._render_timer.isActive())
        self.assertEqual(renders, [True, False])
        self.assertEqual(self._pending_texts(qt_canvas)[(0, 1)], PENDING_PROGRESS_TEXT.format(1, 2))

    @staticmethod
    def _pending_texts(qt_canvas) -> dict:
        """What each place that waits for its plot shows."""
        parser = qt_canvas._parser
        if hasattr(parser, '_pending_texts'):
            return {place: text.get_text() for place, text in parser._pending_texts.items()}
        return {place: cell.getItem(0, 0).text for place, cell in parser._pending_cells.items()}

    def test_a_place_dropped_shows_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                dropped = canvas.plots[0][1]

                canvas.plots[0][1] = None
                qt_canvas.drop_pending_place(0, 1)

                self.assertEqual(self._pending_shown(qt_canvas), {(0, 0), (1, 0)})
                self.assertFalse(qt_canvas.draw_plot(dropped))
                self.assertEqual([len(stacks) for stacks in self._drawn(qt_canvas)], [0, 0, 0])

    def test_a_redraw_keeps_waiting_for_the_plots_still_pending(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                qt_canvas.draw_plot(canvas.plots[1][0])

                qt_canvas.set_canvas(canvas)

                self.assertEqual(self._pending_shown(qt_canvas), {(0, 0), (0, 1)})
                drawn = self._drawn(qt_canvas)
                self.assertEqual([len(stacks) for stacks in drawn], [0, 0, 1])

    def test_another_canvas_is_drawn_whole(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                pending = _canvas()
                qt_canvas = self._qt_canvas(backend, pending, _places(pending))

                other = _canvas()
                qt_canvas.set_canvas(other)

                self.assertEqual(self._pending_shown(qt_canvas), set())
                self.assertEqual([len(stacks) for stacks in self._drawn(qt_canvas)], [1, 2, 1])
                self.assertFalse(qt_canvas.draw_plot(pending.plots[0][0]))

    def test_a_plot_whose_data_arrive_while_another_is_focused_is_drawn_once_the_focus_ends(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                parser = qt_canvas._parser
                qt_canvas.draw_plot(canvas.plots[1][0])
                parser.set_focus_plot(parser._plot_impl_plot_lut[id(canvas.plots[1][0])][0])
                qt_canvas.set_canvas(canvas)

                drawn_while_focused = qt_canvas.draw_plot(canvas.plots[0][0])
                qt_canvas.unfocus_plot()
                qt_canvas.set_canvas(canvas)

                self.assertFalse(drawn_while_focused)
                self.assertEqual(self._pending_shown(qt_canvas), {(0, 1)})
                self.assertEqual([len(stacks) for stacks in self._drawn(qt_canvas)], [1, 0, 1])

    def test_each_ruler_is_drawn_once_on_each_plot_as_the_plots_are_drawn(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _shared_pair()
                first, second = canvas.plots[0]
                first.add_ruler(Ruler(name='R1', xy=(T0 + HOUR // 2, 0.5), color='#FF0000'))
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                parser = qt_canvas._parser
                qt_canvas.draw_plot(first)
                impl = parser._plot_impl_plot_lut[id(first)][0]
                begin, end = parser.get_oaw_axis_limits(impl, 0)
                # Placed by the user while the data of the second plot are read.
                qt_canvas._add_ruler_at(impl, first, parser.transform_value(impl, 0, (begin + end) / 2, inverse=True),
                                        0.5)

                qt_canvas.draw_plot(second)
                qt_canvas.draw_plot(second)
                qt_canvas.drop_pending_place(0, 1)

                names = {ruler.name for ruler in parser.get_rulers()}
                per_plot = Counter((ruler.name, id(ruler.ax if backend == 'matplotlib' else ruler.plot))
                                   for ruler in parser.get_rulers())
                self.assertEqual(len(names), 2)
                self.assertEqual(set(per_plot.values()), {1})
                self.assertEqual(len(per_plot), 4)

    def test_a_plot_drawn_while_a_ruler_is_dragged_takes_the_rulers_once_the_drag_ends(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _shared_pair()
                first, second = canvas.plots[0]
                first.add_ruler(Ruler(name='R1', xy=(T0 + HOUR // 2, 0.5), color='#FF0000'))
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                qt_canvas.draw_plot(first)
                ruler = qt_canvas._parser.get_rulers()[0]

                qt_canvas._ruler_drag = (None, first, ruler)
                qt_canvas.draw_plot(second)
                while_dragged = len(qt_canvas._parser.get_rulers())
                qt_canvas._ruler_drag = None
                end = time.monotonic() + 0.5
                while time.monotonic() < end:
                    self.app.processEvents()

                self.assertEqual(while_dragged, 1)
                self.assertEqual(len(qt_canvas._parser.get_rulers()), 2)

    def test_a_focused_plot_stays_shown_while_the_others_are_drawn_once_the_focus_ends(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                focused = canvas.plots[1][0]
                qt_canvas.draw_plot(focused)
                qt_canvas._full_screen_mode_on(qt_canvas._parser._plot_impl_plot_lut[id(focused)][0])
                self.app.processEvents()

                # The plot of the place the focused one takes now, and the last plot.
                drawn = [qt_canvas.draw_plot(canvas.plots[0][0]), qt_canvas.draw_plot(canvas.plots[0][1])]
                self.app.processEvents()
                shown_while_focused = self._shown(qt_canvas, focused)
                qt_canvas._full_screen_mode_off()
                self.app.processEvents()

                self.assertEqual(drawn, [False, False])
                self.assertTrue(shown_while_focused)
                self.assertTrue(all(self._shown(qt_canvas, plot) for column in canvas.plots for plot in column))

    def test_the_places_of_a_canvas_no_longer_shown_are_left_alone(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                pending = _canvas()
                qt_canvas = self._qt_canvas(backend, pending, _places(pending))
                shown = _canvas()
                qt_canvas.set_canvas(shown)
                drawn = self._drawn(qt_canvas)

                qt_canvas.drop_pending_place(0, 0)
                qt_canvas.draw_plot(shown.plots[0][1])

                self.assertEqual(self._drawn(qt_canvas), drawn)
                self.assertTrue(all(self._shown(qt_canvas, plot) for column in shown.plots for plot in column))

    def test_a_plot_drawn_after_a_zoom_on_the_plots_it_shares_time_with_takes_their_window(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                whole_canvas = _shared_pair()
                whole = self._qt_canvas(backend, whole_canvas)
                self._zoom(whole, whole_canvas.plots[0][0])
                canvas = _shared_pair()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                first, second = canvas.plots[0]
                qt_canvas.draw_plot(first)

                self._zoom(qt_canvas, first)
                qt_canvas.draw_plot(second)
                self.app.processEvents()

                self.assertEqual([self._x_window(qt_canvas, plot) for plot in canvas.plots[0]],
                                 [self._x_window(whole, plot) for plot in whole_canvas.plots[0]])

    def test_a_plot_drawn_with_no_zoom_meanwhile_keeps_the_window_it_was_drawn_over(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _shared_pair()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                qt_canvas.draw_plot(canvas.plots[0][0])

                with patch.object(BackendParserBase, '_x_axis_update_callback', autospec=True) as x_update:
                    qt_canvas.draw_plot(canvas.plots[0][1])

                self.assertEqual([call for call in x_update.call_args_list if 'only' in call.kwargs], [])

    def test_a_slider_moved_while_a_plot_it_moves_with_waits_is_followed_by_that_plot(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _slider_pair()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                first, second = canvas.plots[0]
                qt_canvas.draw_plot(first)

                if backend == 'pyqt':
                    first.slider.setValue(7)
                else:
                    first.slider.set_val(7)
                qt_canvas.draw_plot(second)
                self.app.processEvents()

                self.assertEqual([plot.slider_last_val for plot in canvas.plots[0]], [7, 7])

    def test_a_zoom_whose_gesture_lasts_until_a_plot_it_moves_is_drawn_can_be_undone(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _shared_pair()
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                first, second = canvas.plots[0]
                qt_canvas.draw_plot(first)
                qt_canvas.drop_history()
                impl = qt_canvas._parser._plot_impl_plot_lut[id(first)][0]
                qt_canvas._mmode = Canvas.MOUSE_MODE_ZOOM

                qt_canvas.stage_view_lim_cmd(impl)
                qt_canvas.draw_plot(second)
                self._zoom(qt_canvas, first)
                qt_canvas.commit_view_lim_cmd(impl)
                qt_canvas.push_view_lim_cmd()

                self.assertTrue(qt_canvas.can_undo())

    def test_the_minimap_waits_for_its_plot_without_running_meanwhile(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = Canvas(1, 1)
                plot = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis()]])
                plot.add_signal(_variable('A'), stack=1)
                canvas.add_plot(plot, 0)
                canvas.show_minimap = True
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                qt_class = type(qt_canvas)

                with patch.object(qt_class, '_update_minimap', autospec=True,
                                  side_effect=qt_class._update_minimap) as update:
                    qt_canvas._update_minimap()
                    end = time.monotonic() + 0.3
                    while time.monotonic() < end:
                        self.app.processEvents()
                    while_pending = update.call_count
                    qt_canvas.draw_plot(plot)

                self.assertLess(while_pending, 5)
                self.assertTrue(qt_canvas._minimap_eligible(canvas))

    def test_the_minimap_of_several_plots_never_shows_while_they_are_drawn(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                canvas.show_minimap = True
                places = _places(canvas)
                plots = {place: canvas.plots[place[0]][place[1]] for place in places}
                # As a Draw leaves them: no plot until its rows are built.
                for column, row in places:
                    canvas.plots[column][row] = None
                qt_canvas = self._qt_canvas(backend, canvas, places)

                shown = []
                for (column, row), plot in plots.items():
                    canvas.plots[column][row] = plot
                    qt_canvas.draw_plot(plot)
                    shown.append(qt_canvas._minimap_eligible(canvas))

                self.assertEqual(shown, [False] * len(plots))

    def test_dropping_the_places_left_pending_finishes_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                canvas.shared_x_axis = True
                for column in canvas.plots:
                    for plot in column:
                        _set_time_range(plot, (T0 + 3 * HOUR, T0 + 4 * HOUR) if column is canvas.plots[1] else
                                        (T0, T0 + HOUR))
                with patch('iplotlib.qt.gui.iplotQtCanvas.QMessageBox') as box:
                    qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                    qt_canvas.draw_plot(canvas.plots[0][0])

                    qt_canvas.drop_pending_places()
                    self.app.processEvents()

                self.assertEqual(box.return_value.exec_.call_count, 0)
                self.assertEqual(qt_canvas._parser.pending_places, {})
                self.assertEqual(self._pending_shown(qt_canvas), set())

    def test_plots_of_other_time_ranges_are_told_once_the_last_plot_is_drawn(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                canvas.shared_x_axis = True
                for column in canvas.plots:
                    for plot in column:
                        _set_time_range(plot, (T0 + 3 * HOUR, T0 + 4 * HOUR) if column is canvas.plots[1] else
                                        (T0, T0 + HOUR))
                with patch('iplotlib.qt.gui.iplotQtCanvas.QMessageBox') as box:
                    qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                    plots = [plot for column in canvas.plots for plot in column]
                    for plot in plots[:-1]:
                        qt_canvas.draw_plot(plot)
                    before_the_last = box.return_value.exec_.call_count
                    qt_canvas.draw_plot(plots[-1])
                    # Its window waits for the user: not within the call that draws the plot, while reading goes on.
                    within_the_last = box.return_value.exec_.call_count
                    self.app.processEvents()

                self.assertEqual(before_the_last, 0)
                self.assertEqual(within_the_last, 0)
                self.assertEqual(box.return_value.exec_.call_count, 1)

    def test_each_plot_drawn_takes_the_mouse_mode_of_the_canvas(self):
        for mode, mouse_mode in ((Canvas.MOUSE_MODE_ZOOM, 'RectMode'), (Canvas.MOUSE_MODE_PAN, 'PanMode')):
            with self.subTest(mode=mode):
                canvas = _canvas()
                qt_canvas = self._qt_canvas('pyqt', canvas, _places(canvas))
                qt_canvas.set_mouse_mode(mode)

                for column in canvas.plots:
                    for plot in column:
                        qt_canvas.draw_plot(plot)

                view_boxes = [impl.vb for column in canvas.plots for plot in column
                              for impl in qt_canvas._parser._plot_impl_plot_lut[id(plot)]]
                self.assertEqual({vb.state['mouseMode'] for vb in view_boxes}, {getattr(view_boxes[0], mouse_mode)})

    def test_the_crosshair_takes_in_each_plot_drawn(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas()
                canvas.mouse_mode = Canvas.MOUSE_MODE_CROSSHAIR
                qt_canvas = self._qt_canvas(backend, canvas, _places(canvas))
                qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)

                for column in canvas.plots:
                    for plot in column:
                        qt_canvas.draw_plot(plot)

                parser = qt_canvas._parser
                impls = [impl for column in canvas.plots for plot in column
                         for impl in parser._plot_impl_plot_lut[id(plot)]]
                covered = [impl for cursor in parser._cursors
                           for impl in (cursor.axes if backend == 'matplotlib' else cursor.plots)]
                self.assertEqual(set(map(id, covered)), set(map(id, impls)))


if __name__ == '__main__':
    unittest.main()
