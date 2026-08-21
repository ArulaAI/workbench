"""Test fixture: base classes for CSG edge and expansion tests."""


class BaseProcessor:
    """A processor that subclasses will extend."""

    def process(self, data):
        return self.validate(data)

    def validate(self, data):
        return data is not None


class Serializer:
    """Mixin for serialization."""

    def serialize(self, obj):
        return str(obj)
