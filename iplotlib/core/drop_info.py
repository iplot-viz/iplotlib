class DropInfo:
    """
    Where something was dropped on the grid of a canvas (see IplotQtCanvas.dropSignal): the row and the column, from
    1, of the cell, or of the top left one of the plot or of the reserved slot there; the stack of the plot under the
    drop, by its key in plot.signals, if the backend tells; and the widget the drag came from.
    """

    def __init__(self, row: int = None, col: int = None, stack=None, source=None):
        self.row = row
        self.col = col
        self.stack = stack
        self.source = source
