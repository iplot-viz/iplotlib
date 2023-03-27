from dataclasses import dataclass

class DropInfo:
    """
    Information to be sent in dropSignal
    """
    def __init__(self, ):
        self.dragged_item = None
        self.row = None
        self.col = None
