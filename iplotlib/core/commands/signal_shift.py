"""
Command for undo/redo of signal shifts.
"""

import weakref
from iplotlib.core.command import IplotCommand
import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class SignalShiftCommand(IplotCommand):
    """
    A command to undo/redo signal shift operations.
    """

    def __init__(self,
                 created_signal,
                 original_signal,
                 affected_plot,
                 stack_num: int,
                 new_row_idx: int,
                 original_row_idx: int,
                 original_stack: str,
                 original_pulse_id: str,
                 original_was_hidden: bool,
                 model,
                 parser,
                 main_window) -> None:
        super().__init__('Shift')
        self._created_signal = created_signal
        self._original_signal = original_signal
        self._affected_plot = affected_plot
        self._stack_num = stack_num
        self._new_row_idx = new_row_idx
        self._original_row_idx = original_row_idx
        self._original_stack = original_stack
        self._original_pulse_id = original_pulse_id
        self._original_was_hidden = original_was_hidden
        self._model = model
        self._parser = parser
        self._main_window = weakref.ref(main_window)

        # Store table row data for redo
        df = model.get_dataframe()
        self._row_data = {col: df.at[new_row_idx, col] for col in df.columns}

    def undo(self):
        """Undo the shift: remove created signal, restore original if hidden."""
        super().undo()
        logger.debug(f"Undo Shift: removing signal {self._created_signal.uid}")

        # Get impl_plot for legend updates
        impl_plot = self._parser._signal_impl_plot_lut.get(self._created_signal.uid) if self._created_signal else None

        # 1. Remove visual line and legend entry
        if self._created_signal and hasattr(self._created_signal, 'lines') and self._created_signal.lines:
            for line in self._created_signal.lines:
                if hasattr(line, 'remove'):  # matplotlib
                    line.remove()
                elif hasattr(line, 'scene') and line.scene():  # pyqtgraph
                    line.scene().removeItem(line)

            # Remove from legend separately (pyqtgraph)
            if impl_plot and hasattr(impl_plot, 'legend') and impl_plot.legend:
                impl_plot.legend.removeItem(self._created_signal.lines[0])

        # 2. Remove signal from plot data structure
        if self._affected_plot and self._created_signal:
            stack_signals = self._affected_plot.signals.get(self._stack_num, [])
            if self._created_signal in stack_signals:
                stack_signals.remove(self._created_signal)

            # Remove from parser lookups
            if self._created_signal.uid in self._parser._signal_impl_plot_lut:
                del self._parser._signal_impl_plot_lut[self._created_signal.uid]

            # Remove from shape lookup so redo creates new lines
            signal_id = id(self._created_signal)
            if signal_id in self._parser._signal_impl_shape_lut:
                del self._parser._signal_impl_shape_lut[signal_id]

        # 3. Remove row from table and alias from model's alias list
        self._model.removeRows(self._new_row_idx, 1)
        alias = self._row_data.get('Alias')
        if alias and hasattr(self._model, 'aliases') and alias in self._model.aliases:
            self._model.aliases.remove(alias)

        # 4. Restore original signal visibility and Stack if it was hidden
        if self._original_was_hidden and self._original_signal:
            # Get impl_plot for original signal
            orig_impl_plot = self._parser._signal_impl_plot_lut.get(self._original_signal.uid)

            if hasattr(self._original_signal, 'lines') and self._original_signal.lines:
                for line in self._original_signal.lines:
                    if hasattr(line, 'set_visible'):  # matplotlib
                        line.set_visible(True)
                    elif hasattr(line, 'setVisible'):  # pyqtgraph
                        line.setVisible(True)

                # Re-add to legend (pyqtgraph)
                if orig_impl_plot and hasattr(orig_impl_plot, 'legend') and orig_impl_plot.legend:
                    label = getattr(self._original_signal, 'label', '') or getattr(self._original_signal, 'name', '')
                    orig_impl_plot.legend.addItem(self._original_signal.lines[0], label)

            # Restore Stack and PulseId in original row
            df = self._model.get_dataframe()
            if 'Stack' in df.columns:
                self._model.setData(
                    self._model.createIndex(self._original_row_idx, df.columns.get_loc('Stack')),
                    self._original_stack,
                    2  # Qt.ItemDataRole.EditRole
                )
            if 'PulseId' in df.columns:
                self._model.setData(
                    self._model.createIndex(self._original_row_idx, df.columns.get_loc('PulseId')),
                    self._original_pulse_id,
                    2  # Qt.ItemDataRole.EditRole
                )

        # 5. Refresh canvas
        self._refresh()

    def __call__(self):
        """Redo the shift: re-add created signal, hide original if needed."""
        super().__call__()
        logger.debug(f"Redo Shift: restoring signal {self._created_signal.uid}")

        # 1. Re-insert row in table
        self._model.insertRows(self._new_row_idx, 1)
        df = self._model.get_dataframe()
        for col_idx, col_name in enumerate(df.columns):
            if col_name in self._row_data:
                self._model.setData(
                    self._model.createIndex(self._new_row_idx, col_idx),
                    self._row_data[col_name],
                    2  # Qt.ItemDataRole.EditRole
                )

        # 2. Re-add signal to plot
        if self._affected_plot and self._created_signal:
            # Clear old lines so process_ipl_signal creates new ones
            if hasattr(self._created_signal, 'lines'):
                self._created_signal.lines = []

            self._created_signal.parent = weakref.ref(self._affected_plot)
            self._affected_plot.add_signal(self._created_signal, stack=self._stack_num)

            # Re-add to parser lookup and process
            impl_plots = self._parser._plot_impl_plot_lut.get(id(self._affected_plot), [])
            if impl_plots:
                impl_plot = impl_plots[self._stack_num - 1] if self._stack_num <= len(impl_plots) else impl_plots[0]
                self._parser._signal_impl_plot_lut[self._created_signal.uid] = impl_plot
                self._parser.process_ipl_signal(self._created_signal)

        # 3. Hide original again and clear Stack if needed
        if self._original_was_hidden and self._original_signal:
            # Get impl_plot for original signal
            orig_impl_plot = self._parser._signal_impl_plot_lut.get(self._original_signal.uid)

            if hasattr(self._original_signal, 'lines') and self._original_signal.lines:
                for line in self._original_signal.lines:
                    if hasattr(line, 'set_visible'):  # matplotlib
                        line.set_visible(False)
                    elif hasattr(line, 'setVisible'):  # pyqtgraph
                        line.setVisible(False)

                # Remove from legend (pyqtgraph)
                if orig_impl_plot and hasattr(orig_impl_plot, 'legend') and orig_impl_plot.legend:
                    orig_impl_plot.legend.removeItem(self._original_signal.lines[0])

            # Clear Stack in original row
            df = self._model.get_dataframe()
            if 'Stack' in df.columns:
                self._model.setData(
                    self._model.createIndex(self._original_row_idx, df.columns.get_loc('Stack')),
                    '',
                    2  # Qt.ItemDataRole.EditRole
                )

        # 4. Refresh canvas
        self._refresh()

    def _refresh(self):
        """Refresh canvas and stats."""
        mw = self._main_window()
        if mw:
            mw.canvasStack.refreshLinks()
            w = mw.canvasStack.currentWidget()
            if w:
                w.check_markers(mw.canvas)
                w.stats(mw.canvas)

    def __str__(self):
        return f"{self.__class__.__name__}({hex(id(self))}) {self.name}"
