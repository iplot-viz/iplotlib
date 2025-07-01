# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


# Description: Sets up a Qt application ready to test with a QtVTKCanvas.
# Author: Jaswant Sai Panchumarti
# Changelog:
#   Sept 2021: -Port to PySide2

from iplotlib.impl.vtk.qt import QtVTKCanvas
from iplotlib.qt.testing import QAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless

_instance = None
_qvtk_canvas = None


class QVTKAppTestAdapter(QAppTestAdapter):
    """Helper class to provide QApplication instances"""

    qapplication = True

    def setUp(self):
        """Creates the QApplication instance"""

        # Simple way of making instance a singleton
        global _instance, _qvtk_canvas
        super().setUp()
        if _qvtk_canvas is None and not self.headless():
            _qvtk_canvas = QtVTKCanvas()
            _qvtk_canvas.setFixedSize(800, 800)

        self.canvas = _qvtk_canvas

    def headless(self):
        return vtk_is_headless()

    def tearDown(self):
        """Deletes the reference owned by self"""
        if not self.headless():
            self.canvas.hide()
            del self.canvas
        super().tearDown()
