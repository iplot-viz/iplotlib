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
from collections import defaultdict

from PySide6.QtCore import QMargins, Qt, Slot, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QMessageBox, QSizePolicy, QVBoxLayout, QMenu

import matplotlib.pyplot as plt
from matplotlib.axes import Axes as MPLAxes
from matplotlib.backend_bases import _Mode, DrawEvent, Event, MouseButton, MouseEvent
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from iplotlib.core import PlotContour, SignalXY, PlotXY
from iplotlib.core.canvas import Canvas
from iplotlib.core.distance import DistanceCalculator
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.qt.gui.IplotQtStatistics import IplotQtStatistics
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.gui.iplotQtMarker import IplotQtMarker
import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class QtMatplotlibCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    dropSignal = Signal(object)

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0
        self._marker_window = IplotQtMarker()
        self._marker_window.dropMarker.connect(self.draw_marker_label)
        self._marker_window.deleteMarker.connect(self.delete_marker_label)

        # Statistics
        self._stats_table = IplotQtStatistics()

        self.info_shared_x_dialog = False

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
        self._mpl_renderer.mpl_connect('pick_event', self.on_pick_legend)

        self.setLayout(self._vlayout)
        self.set_canvas(kwargs.get('canvas'))
        self.setAcceptDrops(True)

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

        self.render()
        super().set_canvas(canvas)

        # Check if plots share time axis
        ranges = []
        plot_stack = []

        if canvas:
            if self._parser._pm.get_value(canvas, 'shared_x_axis'):
                if not self.info_shared_x_dialog:
                    self.info_shared_x_dialog = True
                    relative = False
                    for row_idx, col in enumerate(canvas.plots, start=1):
                        for col_idx, plot in enumerate(col, start=1):
                            if plot:
                                axis = plot.axes[0]
                                if not axis.is_date:
                                    relative = True
                                ranges.append((axis.original_begin, axis.original_end))
                                plot_stack.append(f"{col_idx}.{row_idx}")

                    dict_ranges = defaultdict(list)
                    # Need to differentiate if it is absolute or relative
                    if relative:
                        max_diff_ns = self._parser._pm.get_value(canvas, 'max_diff')
                    else:
                        max_diff_ns = self._parser._pm.get_value(canvas, 'max_diff') * 1e9
                    for idx, uniq_range in enumerate(ranges):
                        if uniq_range == ranges[0]:
                            dict_ranges[uniq_range].append(plot_stack[idx])
                        # If the difference of the ranges is less than 1 second, we consider them equal
                        elif abs(uniq_range[0] - ranges[0][0]) <= max_diff_ns and abs(
                                uniq_range[1] - ranges[0][1]) <= max_diff_ns:
                            dict_ranges[ranges[0]].append(plot_stack[idx])
                        else:
                            dict_ranges[uniq_range].append(plot_stack[idx])

                    # If there is more than one element in the dictionary it means that there is more than one time
                    # range
                    if len(dict_ranges) > 1:
                        box = QMessageBox()
                        box.setIcon(QMessageBox.Icon.Information)
                        message = "There are plots with different time range:\n"
                        for i, stacks in enumerate(dict_ranges.values(), start=1):
                            plots_str = ", ".join(stacks)
                            message += f"Time range {i}: Plots {plots_str}\n"

                        box.setText(message)
                        box.exec_()
            else:
                self.info_shared_x_dialog = False

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

    def check_markers(self, canvas: Canvas):
        # Check if there are signals in the table that are no longer used
        markers_signals = self.get_signals(canvas)
        markers_signals_uid = [signal.uid for signal in markers_signals]

        for signal_uid in self._marker_window.get_markers_signal():
            if signal_uid not in markers_signals_uid:
                self._marker_window.remove_signal(signal_uid)
            else:
                # Check signal markers stack
                prev_stack = self._marker_window.get_stack(signal_uid)
                idx = markers_signals_uid.index(signal_uid)
                signal_element = markers_signals[idx]
                current_stack = f"{signal_element.parent.id[0]}.{signal_element.parent.id[1]}.{signal_element.id}"
                if prev_stack != current_stack:
                    self._marker_window.refresh_stack(signal_element, current_stack)

    def get_signals(self, canvas: Canvas):
        signal_list = []
        for row_idx, col in enumerate(canvas.plots, start=1):
            for col_idx, plot in enumerate(col, start=1):
                if plot:
                    for stack in plot.signals.values():
                        for signal in stack:
                            if isinstance(signal, SignalXY):
                                signal_list.append(signal)
        return signal_list

    def get_signal_marker(self, plot_id, signal_uid):
        # Get signal and ax
        for idxCol, col in enumerate(self._parser.canvas.plots):
            for idxPlot, plot in enumerate(col):
                if plot:
                    if plot.id == plot_id:
                        # Get signal
                        for signals in plot.signals.values():
                            for signal in signals:
                                if signal.uid == signal_uid and isinstance(signal, SignalXY):
                                    ax = self._parser._signal_impl_plot_lut.get(signal.uid)  # type: MPLAxes
                                    return signal, ax

    def get_marker_row(self, signal: SignalXY, marker_name: str):
        for i, marker in enumerate(signal.markers_list):
            if marker.name == marker_name:
                return i

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

    def stats(self, canvas: Canvas):
        info_stats = []
        signals = self.get_signals(canvas)
        if signals:
            for signal in signals:
                if isinstance(signal, SignalXY):
                    mpl_axes = self._parser._signal_impl_plot_lut.get(signal.uid)
                    if mpl_axes is None:
                        continue
                    info_stats.append((signal, mpl_axes))
            self._stats_table.fill_table(info_stats)

    def autoscale_y(self, impl_plot):
        """
            Autoscale the Y axis of a single PlotXY and store the action for undo/redo
        """
        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
        if hasattr(ci, 'plot'):
            plot = ci.plot()
            if isinstance(plot, PlotXY):
                # Stage a command to obtain original view limits
                self.stage_view_lim_cmd()

                # Autoscale on Y axis for the given plot
                self._parser.autoscale_y_axis(impl_plot)

                # Commit staged command
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd()

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
        # Stage a command to obtain original view limits
        self.stage_view_lim_cmd()

        for ax in axes:
            ci = self._parser._impl_plot_cache_table.get_cache_item(ax)
            if not hasattr(ci, 'plot'):
                continue
            plot = ci.plot()
            if not isinstance(plot, PlotXY):
                continue

            # Autoscale on Y axis for the given plot
            self._parser.autoscale_y_axis(ax)

        # Commit staged command
        while len(self._staging_cmds):
            self.commit_view_lim_cmd()

        # Push committed command
        while len(self._commitd_cmds):
            self.push_view_lim_cmd()

        # Redraw canvas to reflect changes
        self._parser.figure.canvas.draw()

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

    def show_stats(self):
        if not self._stats_table.isVisible():
            self._stats_table.show()
        elif self._stats_table.isMinimized():
            self._stats_table.showNormal()
        else:
            self._stats_table.raise_()
            self._stats_table.activateWindow()

    def undo(self):
        self._parser.undo()
        self.render()

    def redo(self):
        self._parser.redo()
        self.render()

    def unfocus_plot(self):
        self._parser.set_focus_plot(None)
        self.info_shared_x_dialog = False

    def drop_history(self):
        return self._parser.drop_history()

    @Slot()
    def render(self):
        self._mpl_renderer.draw()
        self._parser.unstale_cache_items()

    # custom event handlers
    def _mpl_draw_finish(self, event: DrawEvent):
        self._draw_call_counter += 1
        self._debug_log_event(event, f"Draw call {self._draw_call_counter}")

    def on_pick_legend(self, event):
        # On the pick event, find the original line corresponding to the legend
        # proxy line, and toggle its visibility.
        legend_line = event.artist

        ax_lines, signal = self._parser.map_legend_to_ax[legend_line]
        visible = True
        for ax_line in ax_lines:
            visible = not ax_line.get_visible()
            ax_line.set_visible(visible)

        # signal.lines = ax_lines
        # Change the alpha on the line in the legend, so we can see what lines
        # have been toggled.
        legend_line.set_alpha(1.0 if visible else 0.2)
        self._parser.figure.canvas.draw()

    def _full_screen_mode_on(self, impl_plot):
        self._parser.set_focus_plot(impl_plot)
        self._refresh_original_ranges = False
        self.refresh()
        self.stats(self.get_canvas())
        self._refresh_original_ranges = True

    def _full_screen_mode_off(self):
        self._parser.set_focus_plot(None)
        self._refresh_original_ranges = False
        self.refresh()
        self.stats(self.get_canvas())
        self._refresh_original_ranges = True

    def _mpl_mouse_press_handler(self, event: MouseEvent):
        """Additional callback to allow for focusing on one plot and returning home after double click"""
        self._debug_log_event(event, "Mouse pressed")

        # If the mouse is over the legend it ignores it
        if event.inaxes and event.inaxes.get_legend() and event.inaxes.get_legend().contains(event)[0]:
            return

        if event.dblclick:
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN] and event.button == MouseButton.RIGHT:
                mpl_axes = event.inaxes
                if not isinstance(mpl_axes, MPLAxes):
                    return
                ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
                if not hasattr(ci, 'plot'):
                    return
                plot = ci.plot()
                if not plot:
                    return

                # Stage a command to obtain original view limits
                self.stage_view_lim_cmd()

                # Reset plot to original view limits
                original_limits = self._parser.get_plot_limits(plot, which='original')
                self._parser.set_plot_limits(original_limits)

                # Commit it.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd()

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
                    new_marker, marker_signal = self._parser.add_marker_scaled(mpl_axes, plot, x_value, y_value)
                    if new_marker is not None:
                        if new_marker not in self._marker_window.get_markers():
                            self._marker_window.add_marker(marker_signal, new_marker)
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
                            f" is 50")
                else:
                    logger.warning("Markers must be enabled in the plot to create signal markers")
        else:
            if event.inaxes is None:
                return
            ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
            if not hasattr(ci, 'plot'):
                return
            plot = ci.plot()
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # Stage a command to obtain original view limits
                # Disable Zoom and Pan in PlotContour
                if isinstance(plot, PlotContour):
                    return
                self.stage_view_lim_cmd()
                return
            if self._mmode == Canvas.MOUSE_MODE_SELECT and event.button == MouseButton.RIGHT:
                # Create menu with autoscale options
                autoscale_menu = QMenu(self)
                autoscale_menu.addAction("Autoscale", lambda: self.autoscale_y(event.inaxes))
                autoscale_menu.addAction("Autoscale All", self.autoscale_all_y)
                if self._parser.canvas.focus_plot is None:
                    autoscale_menu.addAction("Focus on plot", lambda: self._full_screen_mode_on(event.inaxes))
                else:
                    autoscale_menu.addAction("Unfocus plot", self._full_screen_mode_off)
                autoscale_menu.popup(event.guiEvent.globalPos())

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
                    box = QMessageBox(self)
                    box.setWindowTitle('Distance')
                    dx, dy, dz = self._dist_calculator.dist()
                    if any([dx, dy, dz]):
                        box.setText(f"dx = {dx}\ndy = {dy}\ndz = {dz}")
                    else:
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
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # commit commands from staging.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd()
                # push uncommitted changes onto the command stack.
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()
                # Update statistics
                self.stats(self.get_canvas())

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
                print("entre las x\n\n")
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
                if row_plot.id == plot.id:
                    return row + 1, column + 1
