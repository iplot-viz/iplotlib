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
Examples for iplotlib usage with data-access requests and custom data-processing.
"""

from os.path import dirname, basename, isfile, join
import glob

__all__ = [basename(f)[:-3] for f in glob.glob(join(dirname(__file__), "*.py")) if
           isfile(f) and not f.endswith('__init__.py')]
