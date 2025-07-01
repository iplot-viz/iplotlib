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


class ConversionHelper:

    @staticmethod
    def to_int(value):
        return ConversionHelper.to_number(value, int)

    @staticmethod
    def to_float(value):
        return ConversionHelper.to_number(value, float)

    @staticmethod
    def to_number(value, type_func):
        if isinstance(value, type_func):
            return value
        if isinstance(value, str):
            if value == '':
                value = '0'
            return type_func(value)
        if type(value).__module__ == 'numpy':
            return type_func(value.item())

    @staticmethod
    def asType(value, to_type):
        if to_type is not None and hasattr(to_type, '__name__'):
            if to_type == type(value):
                return value
            if to_type.__name__ == 'float64' or to_type.__name__ == 'float':
                return ConversionHelper.to_float(value)
            if to_type.__name__ == 'int64' or to_type.__name__ == 'int':
                return ConversionHelper.to_int(value)

        return value
