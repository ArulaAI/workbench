// Module-level constants (should match ts-constant)
const MAX_RETRIES = 3;
const API_BASE_URL = "https://api.example.com";
const DEFAULT_TIMEOUT_MS = 30000;

// NOT constants — camelCase or inside functions
const myVariable = "hello";
const getData = () => fetch("/api");

function doStuff() {
  const LOCAL_CONST = 42;
  return LOCAL_CONST;
}

class MyClass {
  method() {
    const METHOD_CONST = 99;
    return METHOD_CONST;
  }
}

export function exported() {
  return MAX_RETRIES;
}
