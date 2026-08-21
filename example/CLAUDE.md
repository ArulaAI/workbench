# Project: Bookshelf

> A personal reading tracker. Add books, organize reading lists, track progress.

## Architecture

- **Language:** TypeScript (frontend), Python 3.12+ (backend)
- **Frontend:** Next.js (App Router), Tailwind CSS, Apollo Client
- **Backend:** FastAPI, Strawberry GraphQL, SQLAlchemy 2.0 async
- **Database:** PostgreSQL
- **Structure:** Monorepo with `src/frontend/` and `src/backend/`

## Conventions

### File Organization
- Frontend: `src/frontend/`
- Backend: `src/backend/`
- Components: `src/frontend/components/`
- Models: `src/backend/app/models/`
- Tests co-located with source files

### Naming
- Frontend files: `kebab-case` (e.g., `book-card.tsx`)
- Backend files: `snake_case` (e.g., `reading_list.py`)
- Components: `PascalCase` (e.g., `BookCard`)
- Functions: `camelCase` (TS), `snake_case` (Python)
- Classes: `PascalCase`

### Code Style
- Prefer explicit over implicit
- Handle errors at the call site
- No magic numbers — use named constants
- Keep functions under 30 lines where possible

### Git
- Branch naming: `speed/task-{id}-{slug}`
- Commit messages: imperative mood, under 72 chars
- One logical change per commit

## Quality Gates

### Backend
- lint: `cd src/backend && ruff check .`
- test: `cd src/backend && python -m pytest`

### Frontend
- lint: `cd src/frontend && npx eslint .`
- typecheck: `cd src/frontend && npx tsc --noEmit`

## Patterns

- SQLAlchemy models use async sessions
- GraphQL resolvers are thin — business logic in service functions
- All API inputs validated before hitting the database
- Empty states handled explicitly in every component

## Dependencies

### Frontend
- next, react, react-dom
- @apollo/client, graphql
- tailwindcss

### Backend
- fastapi[standard]
- strawberry-graphql[fastapi]
- sqlalchemy[asyncio], asyncpg
- ruff (linting)
- pytest (testing)
