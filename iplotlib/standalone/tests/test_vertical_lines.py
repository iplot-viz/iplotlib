"""A signal can show a vertical line through each of its points while it shows few of them (vertical_lines, a line
style for the canvas, the plot or the signal): in its color and line size and the style chosen, across the whole
height of the plot, through the samples drawn in the view, following them as the view changes, hidden and removed with
the signal."""

import os
import unittest

import numpy as np
from PySide6.QtGui import QColor

from iplotlib.core.canvas import Canvas
from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class VerticalLinesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _draw(self, backend, x, y=None, level='canvas', vertical_lines='Solid', canvas_options=None, **signal_options):
        """A canvas with a signal sampled at `x`, asking for vertical lines at `level`, drawn by `backend`."""
        canvas = Canvas(1, 1, title='vertical lines', **(canvas_options or {}))
        plot = PlotXY()
        signal = SignalXY(label='s', **signal_options)
        signal.data_access_enabled = False
        y = np.arange(len(x), dtype=float) if y is None else np.asarray(y, dtype=float)
        signal.set_data([np.asarray(x, dtype=float), y])
        plot.add_signal(signal)
        canvas.add_plot(plot, 0)
        setattr({'canvas': canvas, 'plot': plot, 'signal': signal}[level], 'vertical_lines', vertical_lines)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(400, 300)
        self.app.processEvents()
        return qt_canvas, signal

    @staticmethod
    def _drawn(qt_canvas, signal):
        """The implementation of the vertical lines of the signal; None without them."""
        drawn = qt_canvas._parser._signal_vertical_lines_lut.get(id(signal))
        return None if drawn is None else drawn[1]

    @classmethod
    def _lines(cls, qt_canvas, signal):
        """Where the vertical lines of the signal are, whether they show and their color; None without them."""
        lines = cls._drawn(qt_canvas, signal)
        if lines is None:
            return None
        if hasattr(lines, 'get_segments'):
            from matplotlib.colors import to_hex
            return ([float(segment[0][0]) for segment in lines.get_segments()], lines.get_visible(),
                    to_hex(lines.get_colors()[0]))
        return ([float(line.value()) for line in lines], all(line.isVisible() for line in lines),
                lines[0].pen.color().name())

    def _zoom(self, backend, qt_canvas, signal, begin, end):
        parser = qt_canvas._parser
        impl_plot = parser._signal_impl_plot_lut.get(parser.signal_lut_key(signal))
        if backend == 'pyqt':
            impl_plot.getViewBox().setXRange(begin, end, padding=0)
        else:
            impl_plot.set_xlim(begin, end)
        self.app.processEvents()

    def test_a_signal_of_few_points_shows_a_vertical_line_through_each_in_its_color(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                # Not the first color of the cycles, which the lines would also get without the signal's.
                qt_canvas, signal = self._draw(backend, [1.0, 2.0, 4.0], color='#d62728')

                self.assertEqual(self._lines(qt_canvas, signal), ([1.0, 2.0, 4.0], True, '#d62728'))

    def test_in_the_line_size_across_the_whole_height(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal = self._draw(backend, [1.0, 2.0], line_size=3)
                lines = self._drawn(qt_canvas, signal)
                size = qt_canvas._parser._pm.get_value(signal, 'line_size')

                if backend == 'pyqt':
                    self.assertEqual({(line.pen.width(), line.angle) for line in lines}, {(size, 90)})
                else:
                    impl_plot = lines.axes
                    self.assertEqual(list(lines.get_linewidths()), [size])
                    self.assertEqual([[y for _, y in segment] for segment in lines.get_segments()], [[0, 1], [0, 1]])
                    self.assertEqual(lines.get_transform(), impl_plot.get_xaxis_transform())

    def test_the_y_range_stays_that_of_the_data(self):
        for backend in BACKENDS:
            # On a log scale pyqtgraph sets the Y range itself, from what the plot holds.
            for log_scale in (False, True):
                with self.subTest(backend=backend, log_scale=log_scale):
                    ranges = []
                    for vertical_lines in ('None', 'Solid'):
                        qt_canvas, signal = self._draw(backend, [1.0, 2.0, 3.0], y=[5.0, 6.0, 5.5],
                                                       vertical_lines=vertical_lines,
                                                       canvas_options=dict(log_scale=log_scale))
                        parser = qt_canvas._parser
                        impl_plot = parser._signal_impl_plot_lut.get(parser.signal_lut_key(signal))
                        ranges.append(impl_plot.getViewBox().viewRange()[1] if backend == 'pyqt'
                                      else list(impl_plot.get_ylim()))

                    self.assertEqual(ranges[1], ranges[0])

    def test_in_the_line_style_chosen(self):
        from matplotlib.collections import LineCollection
        from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import LINESTYLE_MAP
        for backend in BACKENDS:
            for style in ('Solid', 'Dashed', 'Dotted'):
                with self.subTest(backend=backend, style=style):
                    qt_canvas, signal = self._draw(backend, [1.0, 2.0], vertical_lines=style)
                    lines = self._drawn(qt_canvas, signal)

                    if backend == 'pyqt':
                        self.assertEqual({line.pen.style() for line in lines}, {LINESTYLE_MAP[style.lower()]})
                    else:
                        expected = LineCollection([], linestyles=style.lower(), linewidths=lines.get_linewidths())
                        self.assertEqual(lines.get_linestyle(), expected.get_linestyle())

    def test_the_plot_or_the_signal_can_ask_for_them_too(self):
        for backend in BACKENDS:
            for level in ('plot', 'signal'):
                with self.subTest(backend=backend, level=level):
                    qt_canvas, signal = self._draw(backend, [1.0, 2.0], level=level)

                    self.assertEqual(self._lines(qt_canvas, signal)[0], [1.0, 2.0])

    def test_none_unless_asked_for(self):
        for backend in BACKENDS:
            for vertical_lines in (None, 'None'):
                with self.subTest(backend=backend, vertical_lines=vertical_lines):
                    qt_canvas, signal = self._draw(backend, [1.0, 2.0], vertical_lines=vertical_lines)

                    self.assertIsNone(self._lines(qt_canvas, signal))

    def test_none_for_a_signal_that_shows_many_points(self):
        many = BackendParserBase.FEW_POINTS + 1
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal = self._draw(backend, np.arange(many))

                self.assertIsNone(self._lines(qt_canvas, signal))

    def test_they_follow_the_points_shown_as_the_view_changes(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal = self._draw(backend, np.arange(100))

                self._zoom(backend, qt_canvas, signal, 10.0, 13.0)

                self.assertEqual(self._lines(qt_canvas, signal)[0], [10.0, 11.0, 12.0, 13.0])

    def test_moved_as_the_view_changes_rather_than_drawn_again(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal = self._draw(backend, np.arange(100))
                self._zoom(backend, qt_canvas, signal, 10.0, 13.0)
                first = self._drawn(qt_canvas, signal)
                kept = list(first) if backend == 'pyqt' else [first]

                self._zoom(backend, qt_canvas, signal, 20.0, 23.0)
                self.assertEqual(self._lines(qt_canvas, signal)[0], [20.0, 21.0, 22.0, 23.0])
                self._zoom(backend, qt_canvas, signal, 30.0, 35.0)
                self.assertEqual(self._lines(qt_canvas, signal)[0], [30.0, 31.0, 32.0, 33.0, 34.0, 35.0])

                now = self._drawn(qt_canvas, signal)
                self.assertTrue(all(any(line is old for old in kept) for line in (now[:4] if backend == 'pyqt'
                                                                                  else [now])))

    def test_only_through_the_samples_drawn(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend, scale='linear'):
                qt_canvas, signal = self._draw(backend, [1.0, 2.0, 3.0, 4.0], y=[np.nan, np.nan, 5.0, 6.0])

                self.assertEqual(self._lines(qt_canvas, signal)[0], [3.0, 4.0])
            with self.subTest(backend=backend, scale='log'):
                qt_canvas, signal = self._draw(backend, [1.0, 2.0, 3.0, 4.0], y=[-1.0, 0.0, 5.0, 6.0],
                                               canvas_options=dict(log_scale=True))

                self.assertEqual(self._lines(qt_canvas, signal)[0], [3.0, 4.0])

    def test_with_extremities_through_the_samples_in_the_view_and_not_the_edges_of_the_window(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend, data='a sample between the edges'):
                # As iplotDataAccess gives it: the value held at the start and at the end of the window read.
                qt_canvas, signal = self._draw(backend, [0.0, 4.0, 10.0], y=[7.0, 7.0, 7.0], extremities=True)

                self.assertEqual(self._lines(qt_canvas, signal)[0], [4.0])
            with self.subTest(backend=backend, data='a zoom'):
                qt_canvas, signal = self._draw(backend, np.arange(100), extremities=True)

                self._zoom(backend, qt_canvas, signal, 10.0, 13.0)

                self.assertEqual(self._lines(qt_canvas, signal)[0], [10.0, 11.0, 12.0, 13.0])

    def test_none_while_streaming(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal = self._draw(backend, [1.0, 2.0, 3.0], canvas_options=dict(streaming=True))
                parser = qt_canvas._parser
                self.assertIsNone(self._lines(qt_canvas, signal))

                signal.set_data([np.array([1.0, 2.0, 3.0, 4.0]), np.arange(4, dtype=float)])
                parser.process_ipl_signal(signal)

                self.assertIsNone(self._lines(qt_canvas, signal))

    def test_hidden_with_the_signal(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal = self._draw(backend, [1.0, 2.0])
                parser = qt_canvas._parser

                parser.set_signal_hidden(signal, True)
                self.assertFalse(self._lines(qt_canvas, signal)[1])
                parser.set_signal_hidden(signal, False)
                self.assertTrue(self._lines(qt_canvas, signal)[1])

                qt_canvas, signal = self._draw(backend, [1.0, 2.0], hidden=True)
                self.assertFalse(self._lines(qt_canvas, signal)[1])

    def test_removed_with_the_signal(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal = self._draw(backend, [1.0, 2.0])
                parser = qt_canvas._parser
                lines = self._drawn(qt_canvas, signal)

                parser.remove_signal(signal)

                self.assertIsNone(self._lines(qt_canvas, signal))
                if backend == 'pyqt':
                    self.assertTrue(all(line.getViewBox() is None for line in lines))
                else:
                    self.assertIsNone(lines.axes)


class VerticalLinesPropertyTest(unittest.TestCase):
    """None by default, inherited from the plot and the canvas, and kept with the other preferences."""

    def test_none_by_default_and_inherited(self):
        from iplotlib.core.property_manager import PropertyManager
        canvas = Canvas(1, 1)
        plot = PlotXY()
        signal = SignalXY()
        plot.add_signal(signal)
        canvas.add_plot(plot, 0)
        pm = PropertyManager()

        # Preferences saved before the property existed do not have it.
        self.assertIn(pm.get_value(signal, 'vertical_lines'), ('None', None))
        canvas.vertical_lines = 'Dashed'
        self.assertEqual(pm.get_value(signal, 'vertical_lines'), 'Dashed')
        plot.vertical_lines = 'None'
        self.assertEqual(pm.get_value(signal, 'vertical_lines'), 'None')

    def test_reset_and_merged_with_the_preferences(self):
        from iplotlib.core.persistence import JSONExporter
        for klass in (Canvas, PlotXY, SignalXY):
            with self.subTest(klass=klass.__name__):
                item = klass()
                item.vertical_lines = 'Dotted'
                item.reset_preferences()
                self.assertIsNone(item.vertical_lines)

                # As saved with a workspace.
                saved = JSONExporter().to_dict(item)
                saved['vertical_lines'] = 'Dotted'
                item.merge(saved)
                self.assertEqual(item.vertical_lines, 'Dotted')
                # Preferences saved before the property existed.
                saved.pop('vertical_lines')
                item.merge(saved)
                self.assertIsNone(item.vertical_lines)

    def test_the_preferences_forms_have_it_with_none_first(self):
        from iplotlib.qt.gui.forms.plotting.canvasForm import CanvasForm
        from iplotlib.qt.gui.forms.plotting.plotForm import PlotXYForm
        from iplotlib.qt.gui.forms.plotting.signalForm import SignalXYForm
        ensure_qapp()
        for form_class in (CanvasForm, PlotXYForm, SignalXYForm):
            with self.subTest(form=form_class.__name__):
                form = form_class()
                widget = next(field['widget'] for field in form.fields if field['property'] == 'vertical_lines')
                # A value not set shows as the first one, and draws no vertical lines.
                self.assertEqual([widget.itemText(i) for i in range(widget.count())],
                                 ['None', 'Solid', 'Dotted', 'Dashed'])


if __name__ == '__main__':
    unittest.main()
