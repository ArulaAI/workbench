---
title: Language Support & Extraction
description: Technical reference for SPEED's language support, tree-sitter parsing, and ast-grep extraction.
---

# Language Support & Extraction

SPEED uses a multi-layered extraction system to build the Codebase Semantic Graph (CSG). This system shifts the burden of understanding the codebase from the agent to the infrastructure, ensuring high-fidelity context without hallucinations.

## The Language Registry

The `LanguageRegistry` is the single source of truth for all language knowledge. It maps file extensions to canonical language names and defines how the pipeline treats each language.

- **Helix Integration**: SPEED vendors a copy of the Helix editor's `languages.toml` for extension-to-name mappings (180+ languages). This is separate from `extraction.toml`, which controls how each language is parsed.
- **Extraction Levels** (defined in `lib/context/data/extraction.toml`): Not every language requires full symbol extraction. Three levels:
    - `rules`: Full symbol and relationship extraction using **ast-grep** (e.g., Python, Go, TypeScript).
    - `skeleton`: Structure-only parsing for large files (e.g., HTML, CSS, JSON).
    - `none`: File-type recognition only, no internal parsing.

## Extraction Engine: tree-sitter + ast-grep

tree-sitter parses every source file into an AST. [ast-grep](https://ast-grep.github.io/) queries that AST using declarative YAML rules to extract symbols and references. Both are required: tree-sitter provides the parse, ast-grep provides the query layer.

### Why ast-grep?
- **Declarative**: Symbol extraction is defined in YAML, not Python code.
- **Cross-Language**: A single rule format works for Go structs, Python classes, and TypeScript interfaces.
- **Predictable**: No LLM calls are involved in symbol extraction, ensuring deterministic results.

### Rule Metadata
Each ast-grep rule in `lib/context/rules/` declares what it produces via `metadata`. This mapping informs the CSG construction:

| Produces | CSG Artifact |
|----------|--------------|
| `node` | A Layer A symbol node (Class, Function, Struct). |
| `node` + `orm: true` | A symbol node with database schema annotations. |
| `edge` | A structural relationship (Inherits, Implements). |
| `reference` | A Layer B usage edge (Attribute access, Method call). |

## Custom Language Support

For languages not built into ast-grep (like Prisma or GraphQL), SPEED uses a custom grammar pipeline:

1.  **Grammar Compilation**: Tree-sitter grammars are compiled to platform-specific shared libraries (`.dylib`/`.so`).
2.  **Registration**: Libraries are registered in `sgconfig.yml`.
3.  **Unified Querying**: Once registered, these languages are queried using the same YAML rule syntax as built-in languages.

## Grammar Detection

SPEED automatically detects installed tree-sitter grammars via pip. If you encounter a warning about "unparseable files" in `speed status`, you can enable full extraction by installing the corresponding grammar package:

```bash
pip install tree-sitter-kotlin tree-sitter-elixir
```

## Adding a New Language

The `speed add-language <lang>` command automates the process. Behind the scenes, it performs three steps:

1.  **Install the Grammar**: The `tree-sitter-{lang}` pip package must be installed first. The command validates this and exits with instructions if missing.
2.  **Define YAML Rules**: The command reads the grammar's `node-types.json` and generates draft `definitions.yml` and `references.yml` rules in `lib/context/rules/{lang}/`. Review and test these with `speed test-rules {lang}`.
3.  **Register in `extraction.toml`**: The command adds a `[{lang}]` section with `extraction = "rules"` to `lib/context/data/extraction.toml` if not already present.
