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


"""
Sets up a Qt application ready for testing.
"""

# Author: Jaswant Sai Panchumarti

import unittest

from PySide6.QtWidgets import QApplication

_instance = None


class QAppTestAdapter(unittest.TestCase):
    """Helper class to provide QApplication instances"""

    qapplication = True

    def setUp(self):
        """Creates the QApplication instance"""

        # Simple way of making instance a singleton
        super().setUp()
        global _instance, _qvtk_canvas
        if _instance is None and not self.headless():
            _instance = QApplication([])

        self.app = _instance

    def headless(self):
        """
        Return True if we are running without a display. Default is True.
        """
        return True

    def tearDown(self):
        """Deletes the QApplication reference owned by self"""
        if not self.headless():
            del self.app
        super().tearDown()
