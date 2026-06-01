# Description: A concrete Qt GUI for a matplotlib canvas.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021:  -Fix orphaned matplotlib figure. [Jaswant Sai Panchumarti]
#               -Fix draw_in_main_thread for when C++ object might have been deleted. [Jaswant Sai Panchumarti]
#               -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]
#   Jan 2022:   -Introduce custom HistoryManagement for zooming and panning with git style revision control
#                [Jaswant Sai Panchumarti]
#               -Introduce distance calculator. [Jaswant Sai Panchumarti]
#               -Refactor and let superclass methods refresh, reset use set_canvas, get_canvas [Jaswant Sai Panchumarti]
#   May 2022:   -Port to PySide6 and use new backend_qtagg from matplotlib[Leon Kos]
import typing
from collections.abc import Collection

import numpy as np
from PySide6.QtCore import QMargins, Qt, Slot, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QMessageBox, QSizePolicy, QVBoxLayout, QMenu

import matplotlib.pyplot as plt
from matplotlib.axes import Axes as MPLAxes
from matplotlib.backend_bases import _Mode, DrawEvent, Event, MouseButton, MouseEvent
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from iplotlib.core import PlotContour, SignalXY, PlotXY, PlotXYWithSlider, PlotContourWithSlider
from iplotlib.core.canvas import Canvas
from iplotlib.core.distance import DistanceCalculator
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.gui.iplotSignalShiftDialog import SignalShiftDialog
import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class QtMatplotlibCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    dropSignal = Signal(object)

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0

        self._mpl_size_pol = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._parser = MatplotlibParser(tight_layout=tight_layout, impl_flush_method=self.draw_in_main_thread, **kwargs)
        self._mpl_renderer = FigureCanvas(self._parser.figure)
        self._mpl_renderer.setParent(self)
        self._mpl_renderer.setSizePolicy(self._mpl_size_pol)
        self._mpl_toolbar = NavigationToolbar(self._mpl_renderer, self)
        self._mpl_toolbar.setVisible(False)

        self._vlayout = QVBoxLayout(self)
        self._vlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vlayout.setContentsMargins(QMargins())
        self._vlayout.addWidget(self._mpl_renderer)

        # GUI event handlers
        self._mpl_renderer.mpl_connect('draw_event', self._mpl_draw_finish)
        self._mpl_renderer.mpl_connect('button_press_event', self._mpl_mouse_press_handler)
        self._mpl_renderer.mpl_connect('button_release_event', self._mpl_mouse_release_handler)
        self._mpl_renderer.mpl_connect('motion_notify_event', self._mpl_mouse_motion_handler)
        self._mpl_renderer.mpl_connect('pick_event', self.on_pick_legend)

        self.setLayout(self._vlayout)
        self.set_canvas(kwargs.get('canvas'))
        self.setAcceptDrops(True)

        self._mouse_impl = None

    # Implement basic superclass functionality
    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""
        prev_canvas = self._parser.canvas

        if prev_canvas != canvas and prev_canvas is not None and canvas is not None:
            self.unfocus_plot()

        self._parser.deactivate_cursor()
        self._parser.process_ipl_canvas(canvas)

        if canvas:
            self.set_mouse_mode(self._mmode or canvas.mouse_mode)
        else:
            self.render()
            return

        self.render()
        super().set_canvas(canvas)

    def _is_signal_visible(self, signal) -> bool:
        """Check if signal is visible (Matplotlib implementation)."""
        if not hasattr(signal, 'lines') or not signal.lines:
            return True  # Assume visible if no lines yet (signal being processed)
        try:
            lines = signal.lines
            if isinstance(lines[0], Collection):
                return lines[0][0].get_visible()  # visibility min data
            else:
                return lines[0].get_visible()
        except (IndexError, AttributeError):
            return True

    def draw_marker_label(self, marker_name, plot_id, signal_uid, xy, color, modify):
        signal, ax = self.get_signal_marker(plot_id, signal_uid)  # type: MPLAxes

        # Creation of the annotations
        if isinstance(signal, SignalXY) and ax:
            if not modify:
                # Create and draw marker
                x = self._parser.transform_value(ax, 0, xy[0], inverse=True)
                y = xy[1]
                ax.annotate(text=marker_name,
                            xy=(x, y),
                            xytext=(x, y),
                            bbox=dict(boxstyle="round,pad=0.3", edgecolor="black", facecolor=color))

                # Get marker row
                row = self.get_marker_row(signal, marker_name)

                # Set marker visibility
                signal.markers_list[row].visible = True
                signal.markers_list[row].color = color
                self._parser.figure.canvas.draw()
            else:
                # Change marker color when it is visible
                annotations = [child for child in ax.get_children() if isinstance(child, plt.Annotation)]
                if annotations:
                    for annotation in annotations:
                        if annotation.get_text() == marker_name:
                            # Set new color property
                            annotation.set_bbox(dict(boxstyle="round,pad=0.3", edgecolor="black", facecolor=color))
                            # Get marker row
                            row = self.get_marker_row(signal, marker_name)
                            signal.markers_list[row].color = color
                            self._parser.figure.canvas.draw()

    def delete_marker_label(self, marker_name, plot_id, signal_uid, delete):
        signal, ax = self.get_signal_marker(plot_id, signal_uid)

        # Get annotations from the axis
        annotations = [child for child in ax.get_children() if isinstance(child, plt.Annotation)]

        # Get marker row
        row = self.get_marker_row(signal, marker_name)

        # Indicate if the marker will be removed or hidden
        if delete:
            signal.delete_marker(row)
        else:
            signal.markers_list[row].visible = False

        # Remove annotations
        if annotations:
            for annotation in annotations:
                if annotation.get_text() == marker_name:
                    annotation.remove()
                    self._parser.figure.canvas.draw()
                    return

    def autoscale_y(self, impl_plot):
        """
            Autoscale the Y axis of a single PlotXY and store the action for undo/redo
        """
        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
        if hasattr(ci, 'plot'):
            plot = ci.plot()
            if isinstance(plot, PlotXY):
                # Stage a command to obtain original view limits
                self.stage_view_lim_cmd(impl_plot)

                # Autoscale on Y axis for the given plot
                self._parser.autoscale_y_axis(impl_plot)

                # Commit staged command
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd(impl_plot)

                # Push committed command
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()

                # Redraw canvas to reflect changes
                self._parser.figure.canvas.draw()

    def autoscale_all_y(self):
        """
            Autoscale the Y axis of all PlotXY instances in the figure and store the action for undo/redo
        """
        axes = self._parser.figure.axes
        for ax in axes:
            ci = self._parser._impl_plot_cache_table.get_cache_item(ax)
            if not hasattr(ci, 'plot'):
                continue
            plot = ci.plot()
            if not isinstance(plot, PlotXY):
                continue

            # Stage a command to obtain original view limits
            self.stage_view_lim_cmd(ax)

            # Autoscale on Y axis for the given plot
            self._parser.autoscale_y_axis(ax)

            # Commit staged command
            while len(self._staging_cmds):
                self.commit_view_lim_cmd(ax)

            # Push committed command
            while len(self._commitd_cmds):
                self.push_view_lim_cmd()

        # Redraw canvas to reflect changes
        self._parser.figure.canvas.draw()

    def _save_svg(self, filename: str):
        self._parser.figure.savefig(filename, format='svg', bbox_inches='tight')

    def set_mouse_mode(self, mode: str):
        super().set_mouse_mode(mode)

        if self._mpl_toolbar:
            self._mpl_toolbar.mode = _Mode.NONE
            self._parser.deactivate_cursor()
        else:
            return
        if self._mmode is None:
            return

        if mode == Canvas.MOUSE_MODE_SELECT:
            self._mpl_toolbar.canvas.widgetlock.release(self._mpl_toolbar)
        elif mode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._mpl_toolbar.canvas.widgetlock.release(self._mpl_toolbar)
            self._parser.activate_cursor()
        elif mode == Canvas.MOUSE_MODE_PAN:
            self._mpl_toolbar.pan()
        elif mode == Canvas.MOUSE_MODE_ZOOM:
            self._mpl_toolbar.zoom()
        elif mode == Canvas.MOUSE_MODE_MARKER:
            if not self._marker_window.isVisible():
                self._marker_window.show()
            elif self._marker_window.isMinimized():
                self._marker_window.showNormal()
            else:
                self._marker_window.raise_()
                self._marker_window.activateWindow()

    def undo(self):
        self._parser.undo()
        self.render()

    def redo(self):
        self._parser.redo()
        self.render()

    @Slot()
    def render(self):
        self._mpl_renderer.draw()

    # custom event handlers
    def _mpl_draw_finish(self, event: DrawEvent):
        self._draw_call_counter += 1
        self._debug_log_event(event, f"Draw call {self._draw_call_counter}")

    def on_pick_legend(self, event):
        # Right-click on legend → open signal preferences
        if hasattr(event, 'mouseevent') and event.mouseevent.button == MouseButton.RIGHT:
            self._show_signal_prefs_menu(event.artist, event.mouseevent)
            return

        legend_line = event.artist
        ax_lines = self._parser.map_legend_to_ax.get(legend_line)
        if ax_lines is None:
            return
        self._toggle_legend_line(legend_line, ax_lines)

    def _show_signal_prefs_menu(self, legend_line, event):
        signal = self._parser._legend_signal_lut.get(legend_line)
        if signal is None:
            return
        menu = QMenu(self)
        menu.addAction("Signal Preferences",
                       lambda s=signal: self.openPlotPreferences.emit(s))
        menu.popup(event.guiEvent.globalPos())

    def _toggle_legend_line(self, legend_line, ax_lines):
        if isinstance(ax_lines, Collection):
            visible = True
            for ax_line in ax_lines:  # Envelope case
                visible = not ax_line.get_visible()
                ax_line.set_visible(visible)
        else:
            visible = not ax_lines.get_visible()
            ax_lines.set_visible(visible)
        legend_line.set_alpha(1.0 if visible else 0.2)
        self._parser.figure.canvas.draw()

    def _full_screen_mode_on(self, impl_plot):
        self._parser.set_focus_plot(impl_plot)
        self.refresh()
        self.stats(self.get_canvas())

    def _full_screen_mode_off(self):
        self._parser.set_focus_plot(None)
        self.refresh()
        self.stats(self.get_canvas())

    def _create_drag_preview(self, dy_offset, dx_offset=0.0):
        """Create/update preview line during drag for Matplotlib."""
        if self._drag_shift_signal is None or self._drag_shift_impl_plot is None:
            return

        signal = self._drag_shift_signal
        ax = self._drag_shift_impl_plot

        # Get the original line's data in display coordinates, then offset
        if not signal.lines:
            return

        original_line = signal.lines[0]
        if isinstance(original_line, typing.List):
            original_line = original_line[0]  # min data
        x_data, y_data = original_line.get_data()
        x_data_shifted = np.array(x_data) + dx_offset if abs(dx_offset) > 1e-10 else x_data
        y_data_shifted = np.array(y_data) + dy_offset

        # Remove old preview line if exists
        if self._drag_shift_preview_line is not None:
            try:
                for line in self._drag_shift_preview_line:
                    line.remove()
            except ValueError:
                pass

        # Create preview line with dashed style matching original color
        self._drag_shift_preview_line = ax.plot(
            x_data_shifted, y_data_shifted,
            linestyle='--',
            alpha=0.6,
            color=original_line.get_color(),
            linewidth=original_line.get_linewidth()
        )
        self._parser.figure.canvas.draw_idle()

    def _remove_drag_preview(self):
        """Remove preview line for Matplotlib."""
        if self._drag_shift_preview_line is not None:
            try:
                for line in self._drag_shift_preview_line:
                    line.remove()
            except ValueError:
                pass
            self._drag_shift_preview_line = None
            if self._parser and self._parser.figure:
                self._parser.figure.canvas.draw_idle()

    def _find_signal_at_event(self, event):
        """
        Find the nearest signal to the mouse event using pixel-distance calculation.
        Returns (signal, impl_plot, y_data_coord) or (None, None, None).
        """
        if event.inaxes is None:
            return None, None, None

        ax = event.inaxes
        ci = self._parser._impl_plot_cache_table.get_cache_item(ax)
        click_px = np.array([event.x, event.y])

        def get_line_pixel_data(line):
            """Transform a matplotlib line to pixel coords for distance calculation."""
            lines_to_check = line if isinstance(line, typing.List) else [line]
            for l in lines_to_check:
                xdata = l.get_xdata()
                ydata = l.get_ydata()
                if xdata is None or ydata is None or len(xdata) == 0:
                    continue
                try:
                    data_coords = np.column_stack([xdata, ydata])
                    pixel_coords = ax.transData.transform(data_coords)
                except (ValueError, TypeError):
                    continue
                return pixel_coords, click_px
            return None

        result = self._find_nearest_signal(ci, get_line_pixel_data)
        if result is not None:
            _, signal = result
            return signal, ax, event.ydata
        return None, None, None

    def _mpl_mouse_motion_handler(self, event: MouseEvent):
        """Handle mouse motion for drag shift preview."""
        if not self._drag_shift_active or self._drag_shift_signal is None:
            return
        if event.inaxes != self._drag_shift_impl_plot:
            return
        if event.ydata is not None:
            self._update_drag_shift(event.ydata, event.xdata)

    def _mpl_mouse_press_handler(self, event: MouseEvent):
        """Additional callback to allow for focusing on one plot and returning home after double click"""
        self._debug_log_event(event, "Mouse pressed")

        on_legend = (event.inaxes and event.inaxes.get_legend()
                     and event.inaxes.get_legend().contains(event)[0])

        if (on_legend and event.button in (MouseButton.LEFT, MouseButton.RIGHT)
                and self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]):
            for legend_line, ax_lines in self._parser.map_legend_to_ax.items():
                contains, _ = legend_line.contains(event)
                if contains:
                    if getattr(self._mpl_toolbar, '_zoom_info', None) is not None:
                        self._mpl_toolbar.release_zoom(event)
                    if getattr(self._mpl_toolbar, '_pan_info', None) is not None:
                        self._mpl_toolbar.release_pan(event)
                    if event.button == MouseButton.LEFT:
                        self._toggle_legend_line(legend_line, ax_lines)
                    else:
                        self._show_signal_prefs_menu(legend_line, event)
                    return

        # If the mouse is over the legend it ignores it
        if on_legend:
            return

        if event.dblclick:
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN] and event.button == MouseButton.RIGHT:
                mpl_axes = event.inaxes
                if not isinstance(mpl_axes, MPLAxes):
                    return
                ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
                plot = ci.plot()
                if not plot:
                    return

                # Stage a command to obtain original view limits
                self.stage_view_lim_cmd(event.inaxes)

                # Reset plot to original view limits
                original_limits = self._parser.get_plot_limits(mpl_axes)
                self._parser.set_plot_limits(original_limits)

                # Commit it.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd(event.inaxes)

                # Push it.
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()

                self.render()
            elif self._mmode in [Canvas.MOUSE_MODE_CROSSHAIR, Canvas.MOUSE_MODE_ZOOM,
                                 Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_MARKER] and event.button == MouseButton.LEFT:
                mpl_axes = event.inaxes
                if not isinstance(mpl_axes, MPLAxes):
                    return
                ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
                if not hasattr(ci, 'plot'):
                    return
                plot = ci.plot()
                x_value = event.xdata
                y_value = event.ydata

                # Markers can only be created if the property 'marker' is not None
                if mpl_axes.get_lines()[0].get_marker() != 'None':
                    # Check if the marker coordinates are correct and if the marker has not already been created
                    new_marker, marker_signal, label_line = self._parser.add_marker_scaled(mpl_axes, plot, x_value,
                                                                                           y_value)
                    if new_marker is not None:
                        if new_marker not in self._marker_window.get_markers():
                            self._marker_window.add_marker(marker_signal, new_marker, label_line)
                            if not self._marker_window.isVisible():
                                self._marker_window.show()
                            elif self._marker_window.isMinimized():
                                self._marker_window.showNormal()
                            else:
                                self._marker_window.raise_()
                                self._marker_window.activateWindow()
                        else:
                            logger.warning(f"The marker {new_marker} is already created")
                    else:
                        logger.warning(
                            f"Cannot add marker {new_marker}: found {marker_signal} samples, but the maximum allowed"
                            f" is 100")
                else:
                    logger.warning("Markers must be enabled in the plot to create signal markers")
        else:
            if event.inaxes is None:
                return
            self._mouse_impl = event.inaxes
            ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)

            # Slider event
            if event.inaxes.get_label() == 'slider':
                self.stats(self.get_canvas())
                return

            if not hasattr(ci, 'plot'):
                return
            plot = ci.plot()
            if event.button == MouseButton.RIGHT:
                if getattr(self._mpl_toolbar, '_zoom_info', None) is not None:
                    self._mpl_toolbar.release_zoom(event)
                if getattr(self._mpl_toolbar, '_pan_info', None) is not None:
                    self._mpl_toolbar.release_pan(event)
                self._show_autoscale_menu(event)
                return
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # Stage a command to obtain original view limits
                # Disable Zoom and Pan for PlotContour and for PlotContourWithSlider
                if isinstance(plot, PlotContour) or isinstance(plot, PlotContourWithSlider):
                    return
                self.stage_view_lim_cmd(event.inaxes)
                return

            # Handle drag shift in Select mode with left click - use native hit-testing
            if self._mmode == Canvas.MOUSE_MODE_SELECT and event.button == MouseButton.LEFT:
                signal, impl_plot, y_coord = self._find_signal_at_event(event)
                if signal is not None and signal.envelope:
                    logger.warning("Shift is not supported for envelope signals.")
                elif signal is not None:
                    # Check if X axis is datetime
                    try:
                        is_datetime = plot.axes[0].is_date
                    except (AttributeError, IndexError):
                        is_datetime = False
                    # Get x coordinate for pulse mode dx support
                    x_coord = event.xdata
                    self._start_drag_shift(impl_plot, signal, y_coord, is_datetime, start_x=x_coord)
                    return
                elif signal is None and event.inaxes is not None:
                    # Hit-test doesn't find envelope signals (no standard lines).
                    # Check if the plot has any envelope signals to inform the user.
                    ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
                    if ci and hasattr(ci, 'signals') and ci.signals:
                        for sig_ref in ci.signals:
                            sig = sig_ref()
                            if sig is not None and getattr(sig, 'envelope', False):
                                logger.warning("Shift is not supported for envelope signals.")
                                break

            if event.button != MouseButton.LEFT:
                return
            if not plot:
                self._dist_calculator.reset()
                return
            if self._mmode == Canvas.MOUSE_MODE_DIST:
                if self._dist_calculator.plot1 is not None:
                    try:
                        is_date = plot.axes[0].is_date
                    except (AttributeError, IndexError):
                        is_date = False
                    x = self._parser.transform_value(event.inaxes, 0, event.xdata)
                    self._dist_calculator.set_dst(x, event.ydata, plot, ci.stack_key)
                    self._dist_calculator.set_dx_is_datetime(is_date)
                    dx, dy, dz = self._dist_calculator.dist()
                    if any([dx, dy, dz]):
                        # Get visible signals from the current plot only
                        plot_signals = self.get_visible_plot_signals(plot)
                        dx_numeric = 0.0 if is_date else float(dx)
                        dialog = SignalShiftDialog(
                            self,
                            dx=dx_numeric,
                            dy=float(dy),
                            dz=float(dz) if dz else 0.0,
                            signals=plot_signals,
                            dx_is_datetime=is_date
                        )
                        if is_date:
                            dialog.set_dx_text(str(dx))
                        dialog.shiftRequested.connect(self.signalShiftRequested.emit)
                        dialog.exec()
                    else:
                        box = QMessageBox(self)
                        box.setWindowTitle('Distance')
                        box.setText("Invalid selection")
                        box.exec_()
                    self._dist_calculator.reset()
                else:
                    x = self._parser.transform_value(event.inaxes, 0, event.xdata)
                    self._dist_calculator.set_src(x, event.ydata, plot, ci.stack_key)

    def _mpl_mouse_release_handler(self, event: MouseEvent):
        self._debug_log_event(event, "Mouse released")
        if event.dblclick:
            pass
        else:
            # Handle drag shift completion in Select mode
            if self._drag_shift_active and self._mmode == Canvas.MOUSE_MODE_SELECT:
                if event.ydata is not None:
                    self._end_drag_shift(event.ydata, event.xdata)
                else:
                    self._cancel_drag_shift()
                self.render()
                return

            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # commit commands from staging.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd(self._mouse_impl)
                # push uncommitted changes onto the command stack.
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()
                # Update statistics
                self.stats(self.get_canvas())

    def _show_autoscale_menu(self, event: MouseEvent):
        if event.inaxes is None:
            return
        ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
        autoscale_menu = QMenu(self)
        autoscale_menu.addAction("Autoscale", lambda: self.autoscale_y(event.inaxes))
        autoscale_menu.addAction("Autoscale All", self.autoscale_all_y)
        if self._parser.canvas.focus_plot is None:
            autoscale_menu.addAction("Focus on plot", lambda: self._full_screen_mode_on(event.inaxes))
        else:
            autoscale_menu.addAction("Unfocus plot", self._full_screen_mode_off)
        autoscale_menu.addSeparator()
        if ci:
            autoscale_menu.addAction("Preferences",
                                     lambda: self.openPlotPreferences.emit(ci.plot()))
        nearest_signal, _, _ = self._find_signal_at_event(event)
        if nearest_signal:
            autoscale_menu.addAction("Signal Preferences",
                                     lambda s=nearest_signal: self.openPlotPreferences.emit(s))
        extender = getattr(self._parser, 'context_menu_extender', None)
        if callable(extender):
            try:
                extender(autoscale_menu)
            except Exception:
                logger.exception("context_menu_extender failed")
        autoscale_menu.popup(event.guiEvent.globalPos())

    def keyPressEvent(self, event: QKeyEvent):
        if event.text() == 'n':
            self.redo()
        elif event.text() == 'p':
            self.undo()

    def _debug_log_event(self, event: Event, msg: str):
        logger.debug(f"{self.__class__.__name__}({hex(id(self))}) {msg} | {event}")

    def dragEnterEvent(self, event):
        """
        This function will detect the drag enter event from the mouse on the main window
        """
        super(QtMatplotlibCanvas, self).dragEnterEvent(event)
        event.accept()

    def dragMoveEvent(self, event):
        """
        This function will detect the drag move event on the main window
        """
        x = event.position().x()
        y = event.position().y()
        height = self._parser.figure.bbox.height
        for axe in self._parser.figure.axes:
            if axe.bbox.x0 < x < axe.bbox.x1 and height - axe.bbox.y0 > y > height - axe.bbox.y1:
                event.accept()
                return
        event.ignore()

    def dropEvent(self, event):
        """
        This function will enable the drop file directly on to the
        main window. The file location will be stored in the self.filename
        """
        super(QtMatplotlibCanvas, self).dropEvent(event)
        plot = self.get_plot(event)

        row, col = self.get_position(plot)
        self.dropInfo.row = row
        self.dropInfo.col = col
        self.dropInfo.dragged_item = event.source().dragged_item
        self.dropSignal.emit(self.dropInfo)
        # row, col = self.get_position(plot)
        # new_data = pd.DataFrame([['codacuda', f"{dragged_item.key}", f'{col}.{row}']],
        #                       columns=['DS', 'Variable', 'Stack'])
        # self.parent().parent().parent().parent().sigCfgWidget._model.append_dataframe(new_data)
        # self.parent().parent().parent().parent().drawClicked()
        event.ignore()

    def get_plot(self, event):
        x = event.position().x()
        y = event.position().y()
        height = self._parser.figure.bbox.height
        for axe in self._parser.figure.axes:
            if axe.bbox.x0 < x < axe.bbox.x1 and height - axe.bbox.y0 > y > height - axe.bbox.y1:
                return self._parser._impl_plot_cache_table.get_cache_item(axe).plot()

    def get_position(self, plot):
        all_plots = self._parser.canvas.plots
        for column, col_plots in enumerate(all_plots):
            for row, row_plot in enumerate(col_plots):
                if row_plot.col == plot.col and row_plot.row == plot.row:
                    return row + 1, column + 1
