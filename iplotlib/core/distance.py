class DistanceCalculator:
    def __init__(self) -> None:
        self.p1 = []
        self.p2 = []
        self.plot1 = None
        self.plot2 = None
        self.stack_key1 = None
        self.stack_key2 = None

    def reset(self):
        self.p1.clear()
        self.p2.clear()
        self.plot1 = None
        self.plot2 = None
        self.stack_key1 = None
        self.stack_key2 = None

    def set_src(self, px, py, plot, stack_key, pz=0.0):
        self.p1 = [px, py, pz]
        self.plot1 = plot
        self.stack_key1 = stack_key

    def set_dst(self, px, py, plot, stack_key, pz=0.0):
        self.p2 = [px, py, pz]
        self.plot2 = plot
        self.stack_key2 = stack_key

    def is_valid(self):
        return self.plot1 == self.plot2 and self.stack_key1 == self.stack_key2 and any(self.p1) and any(self.p2)

    def dist(self):
        if self.is_valid():
            return self.p2[0] - self.p1[0], self.p2[1] - self.p1[1],  self.p2[2] - self.p1[2]
        else:
            return None, None, None
