# speed ci demo

A small project that turns on every speed ci check. See README.md.

## Quality Gates

- lint: python3 -m py_compile app.py run_tests.py
- typecheck: python3 -c "import app"
- test: python3 run_tests.py
- e2e: python3 -c "from app import add; assert add(2, 2) == 4"
- api: python3 -c "print('api contract ok')"
