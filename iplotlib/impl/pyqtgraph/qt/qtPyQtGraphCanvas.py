from PySide6.QtCore import QMargins, Qt, Signal, QEvent
from PySide6.QtWidgets import QVBoxLayout, QMenu, QMessageBox

from iplotlib.core import Canvas, PlotXY, PlotContour, SignalXY
from iplotlib.core.distance import DistanceCalculator
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
import iplotLogging.setupLogger as Sl
from pyqtgraph import PlotItem, TextItem

logger = Sl.get_logger(__name__)


class QtPyQtGraphCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    dropSignal = Signal(object)

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0

        self._parser = PyQtGraphParser(tight_layout=tight_layout, impl_flush_method=self.draw_in_main_thread, **kwargs)

        self._vlayout = QVBoxLayout(self)
        self._vlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vlayout.setContentsMargins(QMargins())
        self._vlayout.addWidget(self._parser.figure)

        self.setLayout(self._vlayout)

        # QMenu
        self.autoscale_menu = None

        # Drag & Drop
        self.setAcceptDrops(True)

    def set_canvas(self, canvas):
        prev_canvas = self._parser.canvas

        if prev_canvas != canvas and prev_canvas is not None and canvas is not None:
            self.unfocus_plot()

        self._parser.deactivate_cursor()
        self._parser.process_ipl_canvas(canvas)

        if canvas:
            self.set_mouse_mode(self._mmode or canvas.mouse_mode)

        # Connect events
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                vb = plot.getViewBox()
                vb.pressed.connect(self._impl_mouse_press_handler)
                vb.released.connect(self._impl_mouse_release_handler)

        super().set_canvas(canvas)

    def get_base_plot(self) -> PlotItem:
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                return plot

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

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
            # Stage a command to obtain original view limits
            self.stage_view_lim_cmd(ax)

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
                self.commit_view_lim_cmd(ax)

            # Push committed command
            while len(self._commitd_cmds):
                self.push_view_lim_cmd()

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
        # self.stats(self.get_canvas())

    def _full_screen_mode_off(self):
        self._parser.set_focus_plot(None)
        self.refresh()

    def _impl_mouse_press_handler(self, view_box, event):
        # self._debug_log_event(event, "Mouse released")

        impl_plot = view_box.parentItem()
        if not impl_plot:
            return

        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
        plot = ci.plot()
        if not plot:
            self._dist_calculator.reset()
            return

        if event.type() == QEvent.GraphicsSceneMouseDoubleClick:
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_MARKER,
                               Canvas.MOUSE_MODE_CROSSHAIR]:
                if event.button() == Qt.MouseButton.RightButton:
                    return

                # Maps from scene coordinates to the coordinate system displayed inside the ViewBox
                system_coord = view_box.mapSceneToView(event.scenePos())
                x_value = system_coord.x()
                y_value = system_coord.y()

                # Markers can only be created if the property 'marker' is not None
                if impl_plot.listDataItems()[0].opts['symbol'] != 'None':  # TODO: review
                    # Check if the marker coordinates are correct and if the marker has not already been created
                    new_marker, marker_signal = self._parser.add_marker_scaled(impl_plot, plot, x_value, y_value)
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
                            f" is 100")
                else:
                    logger.warning("Markers must be enabled in the plot to create signal markers")

            elif self._mmode in [Canvas.MOUSE_MODE_SELECT]:
                self.autoscale_menu = None
        else:
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                if event.type() == QEvent.GraphicsSceneMousePress:
                    # Stage a command to obtain original view limits
                    # Disable Zoom and Pan in PlotContour
                    if isinstance(plot, PlotContour):
                        return
                    elif event.button() == Qt.MouseButton.RightButton:
                        return
                    self.stage_view_lim_cmd(impl_plot)
                    return

            elif self._mmode == Canvas.MOUSE_MODE_SELECT:
                self.autoscale_menu = None

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
                    x = self._parser.transform_value(impl_plot, 0, x_value)
                    self._dist_calculator.set_src(x, y_value, plot, ci.stack_key)


    def _impl_mouse_release_handler(self, view_box, event):
        # self._debug_log_event(event, "Mouse released")

        impl_plot = view_box.parentItem()
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
