# Bookshelf — SPEED Example Project

A complete example project with pre-written specs, ready to run through the SPEED pipeline. Use this to learn how SPEED works before writing your own specs.

## What's included

```
example/
  CLAUDE.md                       # Project conventions + quality gates
  speed.toml                      # SPEED configuration
  specs/
    product/
      overview.md                 # Product vision (mission, personas, anti-goals)
      bookshelf.md                # Product spec (features, acceptance criteria)
    tech/
      bookshelf.md                # Tech spec (tables, API, validation)
    design/
      bookshelf.md                # Design spec (pages, components, states)
  src/
    backend/app/                  # Empty Python package (scaffold)
    frontend/                     # Minimal Next.js scaffold
```

## How to use

### 1. Copy into a fresh repo

```bash
mkdir my-bookshelf && cd my-bookshelf
git init

# Copy the example files
cp -r /path/to/speed/example/* .
cp -r /path/to/speed/example/.* . 2>/dev/null || true

# Install SPEED as a subdirectory (pick one)
git clone git@github.com:speed-org/SPEED.git speed        # clone
# — or —
git submodule add git@github.com:speed-org/SPEED.git speed # submodule
# — or —
cp -r /path/to/speed speed              # copy
```

### 2. Review the specs

Read the three spec files to understand what SPEED will build:

- **Product spec** (`specs/product/bookshelf.md`): What features exist, acceptance criteria
- **Tech spec** (`specs/tech/bookshelf.md`): Database tables, GraphQL API, validation rules
- **Design spec** (`specs/design/bookshelf.md`): Pages, components, states

### 3. Run the pipeline

```bash
# Validate specs for consistency
./speed/speed validate specs/

# Generate the task plan
./speed/speed plan specs/tech/bookshelf.md --specs-dir specs/

# Review the plan
./speed/speed status

# Execute tasks
./speed/speed run

# Review and integrate
./speed/speed review
./speed/speed coherence
./speed/speed integrate
```

## What to expect

The Architect will decompose the bookshelf spec into roughly 6 tasks:

1. Database models (authors, books tables)
2. Database models (reading_lists, reading_list_items tables)
3. GraphQL queries (books, authors, readingLists, searchBooks)
4. GraphQL mutations (createBook, updateBook, deleteBook)
5. GraphQL mutations (createReadingList, addBookToList, removeBookFromList)
6. Frontend components (BookCard, ReadingListCard, pages)

Tasks 1 and 2 run first (no dependencies). Tasks 3-5 depend on models. Task 6 depends on the API being defined.

## Notes

- You need a supported AI coding agent CLI installed (e.g., `claude`)
- The example doesn't include a working backend or frontend — SPEED builds those from the specs
- See [Getting Started](../docs/getting-started.md) for a full walkthrough
