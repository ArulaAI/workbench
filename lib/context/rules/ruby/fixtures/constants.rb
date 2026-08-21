# Module-level constants (should match ruby-constant)
MAX_RETRIES = 3
API_BASE_URL = "https://api.example.com"
DEFAULT_TIMEOUT_MS = 30000

# NOT constants — lowercase
my_variable = "hello"

class MyClass
  CLASS_CONST = "inside class"

  def method
    local_var = 42
    local_var
  end
end

module MyModule
  def helper
    true
  end
end
