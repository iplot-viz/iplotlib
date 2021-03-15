
class Event:

    BOUNDS_CHANGED = "bounds_changed"

    def __init__(self, type):
        self.type = type


class CanvasEvent(Event):
    pass


class PlotEvent(Event):

    def __init__(self, type):
        super().__init__(type)


class AxisEvent(Event):
    pass


class SignalEvent(Event):
    pass
