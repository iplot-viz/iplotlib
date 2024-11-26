class HierarchicalProperty:
    def __init__(self, name, default=None):
        self.name = name
        self.default = default
        self.local_name = f"_{name}"

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
        setattr(instance, self.local_name, value)

    def __delete__(self, instance):
        if hasattr(instance, self.local_name):
            delattr(instance, self.local_name)
