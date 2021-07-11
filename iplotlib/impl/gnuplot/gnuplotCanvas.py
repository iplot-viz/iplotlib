from queue import Queue
from subprocess import Popen, PIPE
from threading import Thread
from concurrent import futures
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot
import re

"""
An presentation independent canvas for using gnuplot
"""


class GnuplotCanvas:

    __GPVAL_TERM_PREFIX = "GPVAL_TERM:"
    __GPVAL_PLOT_PREFIX = "GPVAL_PLOT:"

    def __init__(self, canvas: Canvas, show_x_axis=True, bmargin=None, tmargin=None):
        self.canvas = canvas
        self.gnuplot_process = Popen(["gnuplot"], shell=False, stdout=PIPE, stdin=PIPE, stderr=PIPE, bufsize=1, universal_newlines=True)
        self.queue = Queue()
        self.thread = Thread(target=self.__gnuplot_output)
        self.thread.daemon = True
        self.thread_stop_flag = False
        self.thread.start()
        self.plot_range = None
        self.terminal_range = None
        self.start_plot_range = None
        self._bounds_history = []
        self._bounds_history_idx = 0
        self.show_x_axis = show_x_axis
        self.bmargin = bmargin
        self.tmargin = tmargin

        self.update_timer = None
        self.update_queue = set()


    def __gnuplot_output(self):
        for line in iter(self.gnuplot_process.stderr.readline, b''):
            if self.thread_stop_flag:
                return

            # print("gnuplot >> " + str(line.rstrip('\n')))

            if line.startswith(self.__GPVAL_TERM_PREFIX):
                m = re.search(self.__GPVAL_TERM_PREFIX+"([0-9-]+) ([0-9-]+) ([0-9-]+) ([0-9-]+)",line)
                if m:
                    (x1, y1, x2, y2) = m.groups()
                    self.terminal_range = (float(x1), float(y1), float(x2), float(y2))

            if line.startswith(self.__GPVAL_PLOT_PREFIX):
                m = re.search(self.__GPVAL_PLOT_PREFIX+"([0-9e\.-]+) ([0-9e\.-]+) ([0-9e\.-]+) ([0-9e\.-]+)", line)
                if m:
                    (x1, y1, x2, y2) = m.groups()
                    self.plot_range = (float(x1), float(y1), float(x2), float(y2))

                    if self.start_plot_range is None:
                        self.start_plot_range = (float(x1), float(y1), float(x2), float(y2))


    def process_layout(self):
        self.write("reset")

        if self.plot_range:
            self.set_bounds(self.plot_range[0], self.plot_range[1], self.plot_range[2], self.plot_range[3], False)

        if len(self.canvas.plots) == 1 and len(self.canvas.plots[0]) == 1:  # Single plot
            self.__process_plot(self.canvas.plots[0][0])
        elif len(self.canvas.plots) >= 1:
            self.write("set multiplot")
            for i, col in enumerate(self.canvas.plots):
                for j, plot in enumerate(col):
                    if plot:
                        self.write("set origin {},{}".format(i/len(self.canvas.plots), 1 - (j + 1) / self.canvas.rows))
                        self.write("set size nosquare {},{}".format(1/self.canvas.cols, 1 / self.canvas.rows))
                        self.__process_plot(plot)
            self.write("unset multiplot")
        else:
            raise Exception(self.__class__.__name__ + " Unsupported layout")

    def __process_plot(self, plot):
        if not plot:
            return

        if not isinstance(plot, Plot):
            raise Exception("Not a plot instance:" + str(plot))

        for stack, signals in plot.signals.items():
            plot_cmd = []
            if not self.show_x_axis:
                self.write("set xtics format ' '")

            if self.bmargin is not None:
                self.write("set bmargin {}".format(self.bmargin))

            if self.tmargin is not None:
                self.write("set tmargin {}".format(self.tmargin))

            for i, signal in enumerate(signals):
                cmd = ["'-'", 'with lines']
                if signal.title and signal.title is not None:
                    cmd.append("title '{}'".format(signal.title))
                if hasattr(signal, "color") and signal.color is not None:
                    cmd.append("lt rgb '{}'".format(signal.color))
                if hasattr(signal, "linesize") and signal.line_size is not None:
                    cmd.append("lw {}".format(str(signal.line_size)))

                plot_cmd.append(" ".join(cmd))

            if len(plot_cmd):
                if plot.title:
                    self.write("set title '{}'".format(plot.title))

                self.write("set autoscale fix")
                self.write("plot " + ",".join(plot_cmd))
                for i, signal in enumerate(signals):
                    data = signal.get_data()
                    dr=None
                    if( isinstance(data, futures.Future)):
                        dr=data.result()
                    else:
                        dr=data
                    if dr[0] is not None and dr[1] is not None:
                        for x, y in zip(dr[0], dr[1]):
                            self.write(str(x) + " " + str(y))
                    self.write("e")

        self.__trigger_bounds_update()

    def process_event(self, event):
        pass

    def prev(self):
        if self._bounds_history_idx > 0:
            self._bounds_history_idx -= 1
            self.__apply_historic_bounds()

    def next(self):
        if self._bounds_history_idx < len(self._bounds_history):
            self._bounds_history_idx += 1
            self.__apply_historic_bounds()

    def get_bounds(self):
        return self.plot_range

    def set_bounds(self, x1, y1, x2, y2, replot=False, save_history=False):
        start_x = x1 if x1 < x2 else x2
        end_x = x1 if x1 >= x2 else x2
        start_y = y1 if y1 < y2 else y2
        end_y = y1 if y1 >= y2 else y2

        self.write("set xrange [{:f}:{:f}] writeback".format(start_x, end_x), True)
        self.write("set yrange [{:f}:{:f}] writeback".format(start_y, end_y), True)

        if replot:
            self.write("replot")
        self.__trigger_bounds_update()

        if save_history:
            if self._bounds_history_idx == 0:
                self._bounds_history.append(self.start_plot_range)
                self._bounds_history_idx += 1
            self._bounds_history.append((x1, y1, x2, y2))
            self._bounds_history_idx += 1



    def reset_bounds(self):
        if self.start_plot_range:
            self.set_bounds(self.start_plot_range[0], self.start_plot_range[1], self.start_plot_range[2], self.start_plot_range[3], True)

    def to_graph(self, screen_x, screen_y):
        gb = self.terminal_range
        pb = self.plot_range
        dpx = pb[0] + (screen_x-gb[0]) * (pb[0] - pb[2]) / (gb[0] - gb[2])
        dpy = pb[1] + (gb[3] - screen_y) * (pb[1] - pb[3]) / (gb[1] - gb[3])
        return (dpx,dpy)

    def write(self, command: str, echo: bool = False):
        # if echo:
        #     print("gnuplot << " + command)

        self.gnuplot_process.stdin.write(command + '\n')

    def cleanup(self):
        if self.thread:
            self.thread_stop_flag = True
        if self.gnuplot_process:
            self.gnuplot_process.kill()

    # This will cause gnuplot to echo plot and screen bounds and will trigger update
    def __trigger_bounds_update(self):
        self.write("print '{}',GPVAL_X_MIN,GPVAL_Y_MIN,GPVAL_X_MAX,GPVAL_Y_MAX".format(self.__GPVAL_PLOT_PREFIX))
        self.write("print '{}',GPVAL_TERM_XMIN,GPVAL_TERM_YMIN,GPVAL_TERM_XMAX,GPVAL_TERM_YMAX".format(self.__GPVAL_TERM_PREFIX))

    def __apply_historic_bounds(self):
        if 0 <= self._bounds_history_idx < len(self._bounds_history):
            bounds = self._bounds_history[self._bounds_history_idx]
            self.set_bounds(bounds[0], bounds[1], bounds[2], bounds[3], replot=True, save_history=False)
