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
