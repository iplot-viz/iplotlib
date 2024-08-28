"""
The command abstraction. 
In iplotlib, a command encodes a user interactive action.
"""

# Author: Jaswant Sai Panchumarti

from abc import ABC, abstractmethod


class IplotCommand(ABC):
    """
    An IplotCommand object has a name and an undo method.
    The command can be redone by simply calling the object.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    @abstractmethod
    def __call__(self):
        """
        Redo the action of this command.
        """
        return

    @abstractmethod
    def undo(self):
        """
        Undo the action of this command.
        """
        return
