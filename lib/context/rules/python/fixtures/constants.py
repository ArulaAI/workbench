# Module-level constants (should match python-constant)
MAX_RETRIES = 3
API_BASE_URL = "https://api.example.com"
COMPLETENESS_FIELDS = ["first_name", "last_name", "email", "phone"]
DEFAULT_TIMEOUT_MS = 30000
SUPPORTED_FORMATS = {"json", "csv", "xml"}

# Type-annotated constant (may or may not match — acceptable either way)
BATCH_SIZE: int = 100

# NOT constants — should NOT match python-constant
_PRIVATE_CACHE = {}
my_variable = "hello"
T = "single char"
Config = "CamelCase"


def some_function():
    """Constants inside functions should NOT match."""
    LOCAL_CONST = 42
    ANOTHER_LOCAL = "nope"
    return LOCAL_CONST


class MyClass:
    """Constants inside classes should NOT match."""
    CLASS_CONST = "not a module constant"

    def method(self):
        METHOD_CONST = 99
        return METHOD_CONST
