from dataclasses import dataclass


@dataclass
class HierarchicalProperty:
    name: str
    default: any

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        self.local_name = f"_{self.name}"

    def __get__(self, instance, owner):
        if instance is None:
            return self
        value = getattr(instance, self.local_name, None)
        if value is not None:
            return value
        if hasattr(instance, 'parent'):
            return getattr(instance.parent, self.name)
        return self.default

    def __set__(self, instance, value):
        if not isinstance(value, HierarchicalProperty):
            setattr(instance, self.local_name, value)

    def __delete__(self, instance):
        if hasattr(instance, self.local_name):
            delattr(instance, self.local_name)

    def get_real_value(self, instance):
        if instance is None:
            raise ValueError("`instance` should be valid.")
        return instance.__dict__.get(self.local_name, None)
