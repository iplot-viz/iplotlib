"""
This module defines a class for calculating 
distance between two points in a plot.
"""

# Author: Jaswant Sai Panchumarti

import pandas as pd


class DistanceCalculator:
    """
    A datetime aware distance calculator.
    """

    def __init__(self) -> None:
        self.p1 = []
        self.p2 = []
        self.plot1 = None
        self.plot2 = None
        self.stack_key1 = None
        self.stack_key2 = None
        self._dx_is_datetime = False

    def reset(self):
        self.p1.clear()
        self.p2.clear()
        self.plot1 = None
        self.plot2 = None
        self.stack_key1 = None
        self.stack_key2 = None
        self._dx_is_datetime = False

    def set_dx_is_datetime(self, val: bool):
        """
        Enforce datetime semantics for x values.
        """
        self._dx_is_datetime = val

    def set_src(self, px, py, plot, stack_key, pz=0.0):
        """
        Set the source point.
        """
        self.p1 = [px, py, pz]
        self.plot1 = plot
        self.stack_key1 = stack_key

    def set_dst(self, px, py, plot, stack_key, pz=0.0):
        """
        Set the destination point.
        """
        self.p2 = [px, py, pz]
        self.plot2 = plot
        self.stack_key2 = stack_key

    def is_valid(self) -> bool:
        return self.plot1 == self.plot2 and self.stack_key1 == self.stack_key2 and any(self.p1) and any(self.p2)

    def dist(self):
        """
        Calculate the distance.
        """
        if self.is_valid():
            # See https://jira.iter.org/browse/IDV-260
            if self._dx_is_datetime:
                dx = pd.Timestamp(self.p2[0], unit='ns') - pd.Timestamp(self.p1[0], unit='ns')
                dx_str = f"{dx.components.days}D" if dx.components.days else ""
                dx_str += f"T{dx.components.hours}H{dx.components.minutes}M{dx.components.seconds}S"
                if dx.components.nanoseconds:
                    dx_str += f"+{dx.components.milliseconds}m"
                    dx_str += f"+{dx.components.microseconds}u"
                    dx_str += f"+{dx.components.nanoseconds}n"
                else:
                    if dx.components.milliseconds:
                        dx_str += f"+{dx.components.milliseconds}m"
                    if dx.components.microseconds:
                        dx_str += f"+{dx.components.microseconds}m"
                dx = dx_str
            else:
                dx = self.p2[0] - self.p1[0]
            dy = self.p2[1] - self.p1[1]
            dz = self.p2[2] - self.p1[2]
            return dx, dy, dz
        else:
            return None, None, None
