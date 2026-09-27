"""Constant ABI for the deliberately closed plain-class runtime protocol."""
CLASS_PROTOCOL_NAMES = (
    "__init__", "__doc__", "__name__",
    # These hooks must not silently inherit the plain-object implementation.
    "__new__", "__slots__", "__getattribute__", "__getattr__", "__setattr__",
    "__delattr__", "__get__", "__set__", "__delete__", "__set_name__",
    "__init_subclass__", "__bool__", "__len__", "__classcell__",
    "__dict__", "__weakref__", # Also reject body definitions of builtin descriptors.
    # Missing builtin type/object attributes are unsupported, NOT absent.
    "__class__", "__bases__", "__base__", "__mro__", "__subclasses__", "mro",
    "__str__", "__repr__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__hash__", "__format__", "__reduce__", "__reduce_ex__", "__sizeof__", "__dir__",
    "__getstate__", "__subclasshook__", "__qualname__", "object",
    "super", "__self__", "__self_class__", "__thisclass__",
    "__annotations__",
)
