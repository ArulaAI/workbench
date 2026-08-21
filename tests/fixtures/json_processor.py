"""Test fixture: subclass that imports from base_processor."""

from tests.fixtures.base_processor import BaseProcessor, Serializer


class JSONProcessor(BaseProcessor):
    """Processes JSON data. Inherits from BaseProcessor."""

    def process(self, data):
        validated = self.validate(data)
        return self.to_json(validated)

    def to_json(self, data):
        return str(data)


class XMLProcessor(BaseProcessor):
    """Processes XML data. Also inherits from BaseProcessor."""

    def process(self, data):
        validated = self.validate(data)
        return self.to_xml(validated)

    def to_xml(self, data):
        return f"<data>{data}</data>"


def run_pipeline():
    """Calls processors, creating call edges."""
    jp = JSONProcessor()
    xp = XMLProcessor()
    jp.process({"key": "value"})
    xp.process("some data")
