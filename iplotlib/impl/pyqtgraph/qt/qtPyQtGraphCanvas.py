import os

from PySide6.QtCore import QMargins, Qt, Signal, QEvent
from PySide6.QtWidgets import QVBoxLayout, QMenu, QMessageBox

import numpy as np
from iplotlib.core import Canvas, PlotXY, PlotContour, SignalXY, PlotContourWithSlider
from iplotlib.core.distance import DistanceCalculator
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.gui.iplotSignalShiftDialog import SignalShiftDialog
import iplotLogging.setupLogger as Sl
from pyqtgraph import PlotItem, TextItem
import pyqtgraph as pg

logger = Sl.get_logger(__name__)


class QtPyQtGraphCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    dropSignal = Signal(object)

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0

        self._parser = PyQtGraphParser(tight_layout=tight_layout, impl_flush_method=self.draw_in_main_thread, **kwargs)

        # Track connected ViewBoxes to avoid duplicate connections
        self._connected_viewboxes = set()

        self._vlayout = QVBoxLayout(self)
        self._vlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vlayout.setContentsMargins(QMargins())
        self._vlayout.addWidget(self._parser.figure)

        self.setLayout(self._vlayout)
        self.set_canvas(kwargs.get('canvas'))

        # QMenu
        self.autoscale_menu = None

        # Drag & Drop
        self.setAcceptDrops(True)

    def set_canvas(self, canvas):
        prev_canvas = self._parser.canvas

        if prev_canvas != canvas and prev_canvas is not None and canvas is not None:
            self.unfocus_plot()
            # Clear tracking set since ViewBoxes will be recreated
            self._connected_viewboxes.clear()

        self._parser.deactivate_cursor()
        self._parser.process_ipl_canvas(canvas)
        self._parser.figure.ci.layout.activate()

        if canvas:
            self.set_mouse_mode(self._mmode or canvas.mouse_mode)

        # Connect events for each plot - only connect if not already connected
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                vb = plot.getViewBox()
                vb_id = id(vb)
                if vb_id not in self._connected_viewboxes:
                    vb.pressed.connect(self._impl_mouse_press_handler)
                    vb.released.connect(self._impl_mouse_release_handler)
                    vb.dragged.connect(self._impl_mouse_drag_handler)
                    self._connected_viewboxes.add(vb_id)

        super().set_canvas(canvas)

    def get_base_plot(self) -> PlotItem:
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                return plot

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

    def _is_signal_visible(self, signal) -> bool:
        """Check if signal is visible (PyQtGraph implementation)."""
        if not hasattr(signal, 'lines') or not signal.lines:
            return True  # Assume visible if no lines yet (signal being processed)
        try:
            return signal.lines[0].isVisible()
        except (IndexError, AttributeError):
            return True

    def draw_marker_label(self, marker_name, plot_id, signal_uid, xy, color, modify):
        signal, ax = self.get_signal_marker(plot_id, signal_uid)  # type: PlotItem

        # Creation of the annotations
        if isinstance(signal, SignalXY) and ax:
            if not modify:
                # Create and draw marker
                x = self._parser.transform_value(ax, 0, xy[0], inverse=True)
                y = xy[1]

                marker_text = TextItem(anchor=(0.5, 0.5),
                                       html=f"""<div style="
                                       background-color:{color};
                                       color:black;
                                       border:1px solid black;
                                       border-radius:4px;
                                       padding:2px 5px;
                                       font-size:12pt;
                                       text-align:center;
                                        ">{marker_name}</div>""")
                marker_text.setPos(x, y)
                ax.addItem(marker_text)

                # Get marker row
                row = self.get_marker_row(signal, marker_name)

                # Set marker visibility
                signal.markers_list[row].visible = True
                signal.markers_list[row].color = color
            else:
                # Change marker color when it is visible
                annotations = [child for child in ax.items if isinstance(child, TextItem)]
                if annotations:
                    for annotation in annotations:
                        if annotation.toPlainText() == marker_name:
                            # Set new color property
                            new_html = f"""<div style="
                                            background-color:{color};
                                            color:black;
                                            border:1px solid black;
                                            border-radius:4px;
                                            padding:2px 5px;
                                            font-size:12pt;
                                            text-align:center;
                                        ">{marker_name}</div>"""

                            annotation.setHtml(new_html)
                            annotation.update()

                            # Get marker row
                            row = self.get_marker_row(signal, marker_name)
                            signal.markers_list[row].color = color

    def delete_marker_label(self, marker_name, plot_id, signal_uid, delete):
        signal, ax = self.get_signal_marker(plot_id, signal_uid)

        # Get annotations from the axis
        annotations = [child for child in ax.items if isinstance(child, TextItem)]

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
                if annotation.toPlainText() == marker_name:
                    ax.removeItem(annotation)
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

                return

    def autoscale_all_y(self):
        """
            Autoscale the Y axis of all PlotXY instances in the figure and store the action for undo/redo
        """
        axes = self._parser.get_canvas_plots()
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

    def save_canvas_image(self, filename: str):
        """Use pyqtgraph exporters instead of QWidget.grab() for accurate rendering."""
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.svg':
            self._save_svg(filename)
        else:
            from pyqtgraph.exporters import ImageExporter
            exporter = ImageExporter(self._parser.figure.scene())
            exporter.parameters()['width'] = self.width()
            exporter.export(filename)
        logger.info(f"Screenshot saved: {os.path.abspath(filename)}")

    def _save_svg(self, filename: str):
        from pyqtgraph.exporters import SVGExporter
        exporter = SVGExporter(self._parser.figure.scene())
        exporter.export(filename)

    def set_mouse_mode(self, mode: str):
        super().set_mouse_mode(mode)

        if self._mmode is None:
            return

        if mode == Canvas.MOUSE_MODE_SELECT:
            self._parser.set_view_box()
        elif mode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._parser.set_view_box_crosshair()
        elif mode == Canvas.MOUSE_MODE_PAN:
            self._parser.set_view_box_pan()
        elif mode == Canvas.MOUSE_MODE_ZOOM:
            self._parser.set_view_box_zoom()
        elif mode == Canvas.MOUSE_MODE_DIST:
            self._parser.set_view_box()
        elif mode == Canvas.MOUSE_MODE_MARKER:
            self._parser.set_view_box()
            if not self._marker_window.isVisible():
                self._marker_window.show()
            elif self._marker_window.isMinimized():
                self._marker_window.showNormal()
            else:
                self._marker_window.raise_()
                self._marker_window.activateWindow()

    def undo(self):
        self._parser.undo()

    def redo(self):
        self._parser.redo()

    def _full_screen_mode_on(self, impl_plot):
        self._parser.set_focus_plot(impl_plot)
        self.refresh()
        self.stats(self.get_canvas())

    def _full_screen_mode_off(self):
        self._parser.set_focus_plot(None)
        self.refresh()
        self.stats(self.get_canvas())

    def _impl_mouse_press_handler(self, view_box, event):
        """Handle mouse press events in PyQtGraph."""
        impl_plot = view_box.parentItem()
        if not impl_plot:
            return

        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
        plot = ci.plot()
        if not plot:
            self._dist_calculator.reset()
            return

        is_double_click = (
                event.type() == QEvent.Type.GraphicsSceneMouseDoubleClick
                or (hasattr(event, 'double') and callable(getattr(event, 'double', None)) and event.double())
        )

        if is_double_click:
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_MARKER,
                               Canvas.MOUSE_MODE_CROSSHAIR]:
                if event.button() == Qt.MouseButton.RightButton:
                    return

                if isinstance(plot, (PlotContour, PlotContourWithSlider)):
                    logger.warning(f"Markers creation is not supported for {type(plot).__name__}")
                    return

                # Markers can only be created if the property 'marker' is not None
                if impl_plot.listDataItems()[0].opts['symbol'] is not None:
                    # Maps from scene coordinates to the coordinate system displayed inside the ViewBox
                    system_coord = view_box.mapSceneToView(event.scenePos())
                    x_value = system_coord.x()
                    y_value = system_coord.y()

                    new_marker, marker_signal, label_line = self._parser.add_marker_scaled(impl_plot, plot, x_value,
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
                            f"Cannot add marker {new_marker}: found {marker_signal} samples, but the maximum allowed is 100")
                else:
                    logger.warning("Markers must be enabled in the plot to create signal markers")

            elif self._mmode == Canvas.MOUSE_MODE_SELECT:
                self.autoscale_menu = None
        else:
            # Single click handling
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                if isinstance(plot, (PlotContour, PlotContourWithSlider)):
                    return
                if event.button() == Qt.MouseButton.RightButton:
                    return
                self.stage_view_lim_cmd(impl_plot)
                return

            elif self._mmode == Canvas.MOUSE_MODE_SELECT:
                self.autoscale_menu = None
                # Handle drag shift with left click
                if event.button() == Qt.MouseButton.LeftButton:
                    signal, y_coord = self._find_signal_at_event(view_box, event)
                    if signal is not None and signal.envelope:
                        logger.warning("Shift is not supported for envelope signals.")
                    elif signal is not None:
                        try:
                            is_datetime = plot.axes[0].is_date
                        except (AttributeError, IndexError):
                            is_datetime = False
                        system_coord = view_box.mapSceneToView(event.scenePos())
                        x_coord = system_coord.x()
                        self._start_drag_shift(impl_plot, signal, y_coord, is_datetime, start_x=x_coord)
                        event.accept()
                    elif ci and hasattr(ci, 'signals') and ci.signals:
                        # Hit-test doesn't find envelope signals (no standard lines).
                        # Check if the plot has any envelope signals to inform the user.
                        for sig_ref in ci.signals:
                            sig = sig_ref()
                            if sig is not None and getattr(sig, 'envelope', False):
                                logger.warning("Shift is not supported for envelope signals.")
                                break

            elif self._mmode == Canvas.MOUSE_MODE_DIST:
                # Maps from scene coordinates to the coordinate system displayed inside the ViewBox
                system_coord = view_box.mapSceneToView(event.scenePos())
                x_value = system_coord.x()
                y_value = system_coord.y()

                if self._dist_calculator.plot1 is not None:
                    try:
                        is_date = plot.axes[0].is_date
                    except (AttributeError, IndexError):
                        is_date = False
                    x = self._parser.transform_value(impl_plot, 0, x_value)
                    self._dist_calculator.set_dst(x, y_value, plot, ci.stack_key)
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
                    x = self._parser.transform_value(impl_plot, 0, x_value)
                    self._dist_calculator.set_src(x, y_value, plot, ci.stack_key)

    def _impl_mouse_release_handler(self, view_box, event):
        """Handle mouse release events in PyQtGraph."""
        impl_plot = view_box.parentItem()

        # Handle drag shift completion in Select mode
        if self._drag_shift_active and self._mmode == Canvas.MOUSE_MODE_SELECT:
            if event is not None:
                system_coord = view_box.mapSceneToView(event.scenePos())
                x_value = system_coord.x()
                y_value = system_coord.y()
                self._end_drag_shift(y_value, x_value)
            else:
                self._cancel_drag_shift()
            return

        if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
            # commit commands from staging.
            while len(self._staging_cmds):
                self.commit_view_lim_cmd(impl_plot)
            # push uncommitted changes onto the command stack.
            while len(self._commitd_cmds):
                self.push_view_lim_cmd()
            # Update statistics
            self.stats(self.get_canvas())

        elif self._mmode in [Canvas.MOUSE_MODE_SELECT]:
            if event is None or event.button() == Qt.MouseButton.LeftButton or event.double():
                return

            # Create menu with autoscale options
            if self.autoscale_menu is None:
                self.autoscale_menu = QMenu(self)
                self.autoscale_menu.addAction("Autoscale", lambda: self.autoscale_y(impl_plot))
                self.autoscale_menu.addAction("Autoscale All", self.autoscale_all_y)
                if self._parser.canvas.focus_plot is None:
                    self.autoscale_menu.addAction("Focus on plot",
                                                  lambda: self._full_screen_mode_on(impl_plot))
                else:
                    self.autoscale_menu.addAction("Unfocus plot", self._full_screen_mode_off)
                self.autoscale_menu.popup(event.screenPos().toPoint())

    def mouse_clicked(self, event):
        if not event.currentItem:
            return
        plot = event.currentItem.parentItem()
        if not plot or not isinstance(plot, PlotItem):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if event.double():
                self._parser.set_focus_plot(plot)
            else:
                pass
        elif event.button() == Qt.MouseButton.RightButton:
            if event.double():
                pass
            else:
                pass

    def mouse_moved(self, pos):
        pass

    def _impl_mouse_drag_handler(self, view_box, event):
        """Handle mouse drag events for preview during drag shift."""
        if not self._drag_shift_active or self._drag_shift_signal is None:
            return

        impl_plot = view_box.parentItem()
        if impl_plot != self._drag_shift_impl_plot:
            return

        if event is None:
            return

        system_coord = view_box.mapSceneToView(event.scenePos())
        x_value = system_coord.x()
        y_value = system_coord.y()
        if y_value is not None:
            self._update_drag_shift(y_value, x_value)

    def _find_signal_at_event(self, view_box, event):
        """
        Find the nearest signal to the event position using pixel-distance calculation.
        Returns (signal, y_data_coord) or (None, None).
        """
        impl_plot = view_box.parentItem()
        if not impl_plot:
            return None, None

        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)

        # Map pixel radius to data-coordinate tolerances for normalization
        scene_pos = event.scenePos()
        view_pos = view_box.mapSceneToView(scene_pos)
        click_x, click_y = view_pos.x(), view_pos.y()

        from PySide6.QtCore import QPointF
        p2 = view_box.mapSceneToView(QPointF(scene_pos.x(), scene_pos.y() + 1.0))
        p3 = view_box.mapSceneToView(QPointF(scene_pos.x() + 1.0, scene_pos.y()))
        # Data units per pixel — invert to get pixels per data unit
        data_per_px_x = abs(p3.x() - view_pos.x())
        data_per_px_y = abs(p2.y() - view_pos.y())
        sx = 1.0 / data_per_px_x if data_per_px_x > 0 else 1.0
        sy = 1.0 / data_per_px_y if data_per_px_y > 0 else 1.0
        click_norm = np.array([click_x * sx, click_y * sy])

        # Precompute x tolerance in data coords for early-exit range check
        tol_x = data_per_px_x * self.PICK_RADIUS_PX

        def get_line_pixel_data(line):
            """Normalize a pyqtgraph line to pixel-equivalent coords for distance calculation."""
            if not hasattr(line, 'getData'):
                return None
            x_data, y_data = line.getData()
            if x_data is None or y_data is None or len(x_data) == 0:
                return None
            x_min, x_max = x_data.min(), x_data.max()
            if not (x_min - tol_x <= click_x <= x_max + tol_x):
                return None
            pixel_coords = np.column_stack([x_data * sx, y_data * sy])
            return pixel_coords, click_norm

        result = self._find_nearest_signal(ci, get_line_pixel_data)
        if result is not None:
            _, signal = result
            return signal, click_y
        return None, None

    def _create_drag_preview(self, dy_offset, dx_offset=0.0):
        """Create/update preview line during drag for PyQtGraph."""
        if self._drag_shift_signal is None or self._drag_shift_impl_plot is None:
            return

        signal = self._drag_shift_signal
        impl_plot = self._drag_shift_impl_plot

        # Get original line data
        if not signal.lines:
            return

        original_line = signal.lines[0]
        x_data, y_data = original_line.getData()
        if x_data is None or y_data is None:
            return

        x_data_shifted = np.array(x_data) + dx_offset if abs(dx_offset) > 1e-10 else x_data
        y_data_shifted = np.array(y_data) + dy_offset

        # Remove old preview line if exists
        self._remove_drag_preview()

        # Get line style from original signal
        pen_color = 'b'
        pen_width = 2
        try:
            original_pen = original_line.opts.get('pen')
            if original_pen:
                pen_color = original_pen.color()
                pen_width = original_pen.width()
        except Exception:
            pass

        # Create preview line with dashed style
        pen = pg.mkPen(color=pen_color, width=pen_width, style=Qt.PenStyle.DashLine)
        self._drag_shift_preview_line = impl_plot.plot(x_data_shifted, y_data_shifted, pen=pen)

    def _remove_drag_preview(self):
        """Remove preview line for PyQtGraph."""
        if self._drag_shift_preview_line is not None:
            try:
                if self._drag_shift_impl_plot is not None:
                    self._drag_shift_impl_plot.removeItem(self._drag_shift_preview_line)
            except Exception:
                pass
            self._drag_shift_preview_line = None
