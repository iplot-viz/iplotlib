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
