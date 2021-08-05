from vtkmodules.vtkRenderingCore import vtkTextProperty
from vtkmodules.vtkRenderingContext2D import vtkContext2D

class CanvasTitleItem(object):
    def __init__(self, title: str):
        self.title = title
        self.appearance = vtkTextProperty()
        self.appearance.SetFontSize(22)
        self.appearance.SetColor(0., 0., 0.)
        self.debug_rect = False

    def Initialize(self, vtkSelf):
        return True

    def Paint(self, vtkSelf, painter: vtkContext2D):

        painter.ApplyTextProp(self.appearance)
        bds = [0., 0., 0., 0.]  # xmin, ymin, width, height
        painter.ComputeStringBounds(self.title, bds)
        rect = bds
        rect[0] += (0.5 * (1. - bds[2]))
        rect[1] += (0.5 * (1. - bds[3]))
        painter.DrawStringRect(rect, self.title)

        # Draw a yellow rect to debug paint region.
        if self.debug_rect:
            pen = painter.GetPen()

            penColor = [0, 0, 0]
            pen.GetColor(penColor)
            penWidth = pen.GetWidth()

            brush = painter.GetBrush()
            brushColor = [0, 0, 0, 0]
            brush.GetColor(brushColor)

            pen.SetColor([200, 200, 30])
            brush.SetColor([200, 200, 30])
            brush.SetOpacity(128)

            painter.DrawPolygon([0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0], 4)

            pen.SetWidth(penWidth)
            pen.SetColor(penColor)
            brush.SetColor(brushColor[:3])
            brush.SetOpacity(brushColor[3])

        return True
