// Module-level constants (should match tsx-constant)
const MAX_RETRIES = 3;
const API_BASE_URL = "https://api.example.com";
const DEFAULT_TIMEOUT_MS = 30000;

// NOT constants — camelCase or inside functions
const myVariable = "hello";

function MyComponent() {
  const LOCAL_CONST = 42;
  return <div>{LOCAL_CONST}</div>;
}

class MyClass {
  method() {
    const METHOD_CONST = 99;
    return METHOD_CONST;
  }
}
