from abc import ABC, abstractmethod

class IplotCommand(ABC):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    @abstractmethod
    def __call__(self):
        return

    @abstractmethod
    def undo(self):
        return
