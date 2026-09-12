"""Repository documentation adapter with no executable-content handling."""
from .base import Unit


def extract(source):
    if not source.text.strip():
        return []
    return [Unit(source, source.path.rsplit("/", 1)[-1],
                 source.path + "::document", 0, len(source.text), "module")]


def bindings(unit): return []
def calls(unit): return []
def candidates(*args): return []
def resources(unit): return []
def observations(unit): return []
def operations(unit): return []
def relations(source): return []
