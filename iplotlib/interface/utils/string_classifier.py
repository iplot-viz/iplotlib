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


class StringType:
    NOT_A_STRING = 1
    MULTI_SPACE = 2
    SINGLE_SPACE = 3
    NON_EMPTY = 4
    EMPTY = 5


def get_string_type(val) -> int:
    if not isinstance(val, str):
        return StringType.NOT_A_STRING

    if val.isspace():
        if len(val) > 1:
            return StringType.MULTI_SPACE
        else:  # len(val) == 1; note: length cannot be zero, because isspace is strict (>=1)
            return StringType.SINGLE_SPACE
    else:
        if len(val):
            return StringType.NON_EMPTY
        else:
            return StringType.EMPTY


def is_a_string(val: str) -> bool:
    return get_string_type(val) != StringType.NOT_A_STRING


def is_multi_space(val: str) -> bool:
    return get_string_type(val) == StringType.MULTI_SPACE


def is_single_space(val: str) -> bool:
    return get_string_type(val) == StringType.SINGLE_SPACE


def is_non_empty(val) -> bool:
    return get_string_type(val) == StringType.NON_EMPTY


def is_empty(val: str) -> bool:
    return get_string_type(val) == StringType.EMPTY
