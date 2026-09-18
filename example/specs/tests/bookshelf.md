# Test Spec: Bookshelf Core

> See [specs/tech/bookshelf.md](../tech/bookshelf.md) for the technical contract under evaluation.
> Product context: [specs/product/bookshelf.md](../product/bookshelf.md). Design: [specs/design/bookshelf.md](../design/bookshelf.md).

## Sources and Review

| Source | Version / revision | Requirements or sections used |
|---|---|---|
| [Tech spec](../tech/bookshelf.md) | commit `6e87b9d`, 2026-08-21 | Data Model (tables, constraints, relationships), GraphQL API (queries, mutations, types), Validation Rules VR-1 to VR-6, Search |
| [Product spec](../product/bookshelf.md) | commit `6e87b9d`, 2026-08-21 | F1 acceptance criteria 1 to 6, F2 criteria 1 to 7, F3 criteria 1 to 4, Out of scope |
| [Design spec](../design/bookshelf.md) | commit `6e87b9d`, 2026-08-21 | Page states (empty, populated, filtered empty), AddBookForm, StatusBadge labels, Responsive Behavior |
| [Product vision](../product/overview.md) | commit `6e87b9d`, 2026-08-21 | MoSCoW priorities (search is Should-have), Won't-have list |
| Project agent file `example/CLAUDE.md` | commit `6e87b9d`, 2026-08-21 | Quality Gates (backend test command), test co-location convention, stack |

Neither the tech spec nor the product spec assigns IDs to its criteria or rules. This spec refers to them by position: `F1-3` is the third acceptance criterion under F1 in the product spec, `VR-4` is the fourth bullet under Validation Rules in the tech spec. Renumbering in a source is a source change and triggers the review below.

- **Spec owner:** Unassigned. The example project has no feature owner.
- **Review status:** Draft
- **Reviewer and review date:** No review has occurred. Written 2026-09-17.

The tech spec predates the RFC template and has no Testing section. Acceptance criteria are therefore taken from the product spec, and risk scenarios carry an author-stated rationale instead of a source row. No implementation exists yet (`src/` is a scaffold), so every scenario is `not_run` and no baseline has been recorded.

## Scope

Covers the Bookshelf Core feature: book management (F1), reading lists (F2), the dashboard (F3), and the `searchBooks` query from the tech spec. Backend behavior is verified through the GraphQL API against a real PostgreSQL database. Schema constraints that back the API checks are verified directly at the database. Page-level behavior from the design spec is verified end to end in a browser. The catalog is grouped by feature area, with separate areas for search, integrity risks, and edge cases.

Nothing is implemented today, so this spec describes the contract the implementation must satisfy rather than the behavior of existing code. There is no existing behavior that must remain unchanged.

Open decisions are listed below. Scenarios against each are written to the settled part of the contract; the open part is not asserted.

| ID | Open decision | Source gap | Scenarios affected |
|---|---|---|---|
| GAP-01 | No mutation reorders books within a list, yet F2-5 requires reordering | Tech spec GraphQL API has no reorder or move operation | F2-5 has no covering scenario |
| GAP-02 | Error contract for rejected mutations: message text, error code, extensions shape | Tech spec Validation Rules say what is rejected, not how | VAL-01 to VAL-09 and EDGE-03 assert "a GraphQL error and no write" only |
| GAP-03 | Whether `%` and `_` in a `searchBooks` query are escaped or act as ILIKE wildcards | Tech spec Search | No scenario; see OOS-08 |
| GAP-04 | Product spec F3-2 requires a want-to-read count; the design spec's stats row shows only total, reading, finished | Product spec vs Design spec | AC-15 asserts the three designed cards only |
| GAP-05 | Default `position` when `addBookToList` omits it; behavior on position collision; whether positions compact after removal | Tech spec API and Validation Rules | AC-05 and AC-12 assert remaining items and relative order, not exact positions |
| GAP-06 | Whether `authorName` reuse is case-insensitive; whether whitespace-only titles count as empty; whether `updatedAt` changes on update | Design spec AddBookForm, tech spec VR-1, Data Model | EDGE-06 uses an identical string; VAL-01 uses the empty string; nothing asserts `updatedAt` changes |

## Test Levels

| Level | Meaning | Tooling | Environment |
|---|---|---|---|
| integration | GraphQL operation executed against the FastAPI app with real SQLAlchemy persistence | pytest via the backend Quality Gates entry in `CLAUDE.md` (`cd src/backend && python -m pytest`); in-process GraphQL client against the Strawberry schema | PostgreSQL test database with the feature's migrations applied, reset between tests |
| db | Schema constraint exercised directly with SQL or a SQLAlchemy session, bypassing the API | Same pytest command; asyncpg or SQLAlchemy async session | Same PostgreSQL test database |
| e2e | Page rendered in a browser against the running frontend and backend | Not configured. `CLAUDE.md` has no `test:` entry under `### Frontend`; see EC-04 | Next.js app and FastAPI app running against the test database |

The `unit` level is not used. Business logic lives in service functions per the project patterns, but the tech spec names no functions, so asserting at the API boundary avoids inventing internal names. Test files follow the project's co-location convention (tests beside source); exact paths are assigned when the tests are authored.

## Entry Conditions

| ID | Condition | Needed for | Status on 2026-09-17 |
|---|---|---|---|
| EC-01 | Application revision under test recorded, with Python and Node versions and the applied migration set | Every scenario | No implementation exists; `src/backend/app` is an empty package |
| EC-02 | PostgreSQL test database with all four tables from the Data Model, resettable per test | integration, db | Not provisioned |
| EC-03 | GraphQL schema exposes every query and mutation in the tech spec's API tables | integration | Not implemented |
| EC-04 | A frontend test runner, a browser driver, and a `test:` entry under `### Frontend` in `CLAUDE.md` | AC-07, AC-08, AC-14, AC-15, AC-16, EDGE-02, EDGE-07, EDGE-08, EDGE-10 | Missing. These scenarios cannot run or receive a red baseline until it exists |
| EC-05 | GAP-01 through GAP-06 decided and the tech spec updated | Exact assertions in the affected scenarios; a scenario for F2-5 | Open |

A failing assertion is the expected red baseline while the feature is unbuilt. A missing test file, an undiscovered selector, an unreachable database, or an unconfigured runner is a setup gap and does not count as a baseline. The example is single-user, so no accounts or credentials are required.

## Scenario Catalog

Scenarios are phrased Given / when / then in one sentence. Fixture handles in backticks (`empty-db`, `seed-books`, `B3`, `L1`) are defined under Fixtures and Test Data; each test establishes its own state. Status values are written as the GraphQL enum (`WANT_TO_READ`) at the API and as the badge label ("Want to Read") on pages.

### Book management

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Given `empty-db`, when `createBook(title: "Dune", authorName: "Frank Herbert")` is called with no isbn or status, then the book is persisted with the contract defaults | integration | Returns a `Book` with a non-empty `id`, `title` "Dune", `author.name` "Frank Herbert", `isbn` null, `status` `WANT_TO_READ`, non-null `createdAt` and `updatedAt`; `book(id)` returns the same values; `books` returns exactly that one book; `authors` returns exactly one author named "Frank Herbert" |
| AC-02 | Given `empty-db`, when `createBook` is called with `isbn: "9780547773742"` and `status: READING`, then the supplied values are persisted | integration | Returned `isbn` is "9780547773742" and `status` is `READING`; a subsequent `book(id)` read returns the same two values |
| AC-03 | Given `seed-books`, when `updateBook(id: B3, status: READING)` is called, then only the status changes | integration | Returns `B3` with `status` `READING`; `title`, `author.name`, and `isbn` are unchanged on re-read; `books(status: READING)` returns exactly `B2` and `B3`; `books` still returns 5 |
| AC-04 | Given `seed-books`, when `updateBook(id: B4, title: "Dune Messiah", authorName: "F. Herbert", isbn: "9780441172696")` is called, then all three fields are persisted | integration | Re-read `B4` has the new title, `author.name` "F. Herbert", and the new isbn; `authors` now includes "F. Herbert"; the other four books are unchanged |
| AC-05 | Given `seed-books` and `seed-lists` with `B1` in `L1`, when `deleteBook(id: B1)` is called, then the book and its list memberships are removed | integration | Returns `true`; `book(id: B1)` returns null; `books` returns 4; `readingList(id: L1).items` contains `B3` and `B5` only, `B3` before `B5`, and `bookCount` is 2 |
| AC-06 | Given `seed-books`, when `books(status: FINISHED)` is queried, then only finished books are returned | integration | Exactly `B1` and `B5`; `books(status: READING)` returns exactly `B2`; `books` with no argument returns all 5 |
| AC-07 | Given `empty-db`, when the Books page (`/books`) loads, then the empty state with an add call to action is shown | e2e | Text "Your bookshelf is empty" is visible, an "Add Book" control is visible and enabled, and no BookCard is rendered |
| AC-08 | Given `seed-books`, when the Books page filter "Reading" is selected, then only reading books are shown | e2e | Exactly one BookCard, for `B2`, with badge label "Reading"; the "Reading" tab shows count 1 and is highlighted; the "All" tab shows count 5 |

### Reading lists

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-09 | Given `empty-db`, when `createReadingList(name: "Book club")` is called with no description, then an empty list is persisted | integration | Returns a `ReadingList` with a non-empty `id`, `name` "Book club", `description` null, `items` `[]`, `bookCount` 0; `readingLists` returns exactly that one list |
| AC-10 | Given `seed-books` and the empty list `L2`, when `addBookToList(readingListId: L2, bookId: B3, position: 1)` is called, then the membership is persisted | integration | Returns a `ReadingListItem` with `book.id` `B3`, `position` 1, and a non-null `addedAt`; `readingList(id: L2).items` is exactly that one item and `bookCount` is 1 |
| AC-11 | Given `seed-lists`, when `readingList(id: L1)` is queried, then each item carries the position it was added with | integration | Exactly three items: `B1` at 1, `B3` at 2, `B5` at 3; `bookCount` is 3; `name` is "Favorites" and `description` is "Comfort re-reads" |
| AC-12 | Given `seed-lists`, when `removeBookFromList(readingListId: L1, bookId: B3)` is called, then the membership is removed and the book itself remains | integration | Returns `true`; `readingList(id: L1).items` contains `B1` and `B5` only, `B1` before `B5`, `bookCount` 2; `book(id: B3)` still returns the book; `books` still returns 5 |
| AC-13 | Given `seed-lists`, when `deleteReadingList(id: L1)` is called, then the list and its items are removed and no book is deleted | integration | Returns `true`; `readingList(id: L1)` returns null; `readingLists` returns only `L2`; `books` returns 5 and `book(id: B1)` returns the book |
| AC-14 | Given `seed-lists`, when the Reading List page for `L1` loads, then its books appear in position order with status badges and remove controls | e2e | Heading "Favorites" with "Comfort re-reads" below it; three rows in the order `B1`, `B3`, `B5`, each showing the book title, the author name, the badge labels "Finished", "Want to Read", "Finished" respectively, and a remove control |

### Dashboard

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-15 | Given `seed-books` and `seed-lists`, when the Dashboard (`/`) loads, then the stats and list summaries match the stored data | e2e | Stats cards read total 5, currently reading 1, finished 2; the reading lists section shows "Favorites" with "3 books" and "Book club" with "0 books" |
| AC-16 | Given `seed-lists`, when the "Favorites" card is activated and then the Books page link is activated, then each navigates to its target | e2e | First navigation lands on `/lists/{L1 id}` with heading "Favorites"; second lands on `/books` with heading "Books" |

### Search

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| SEARCH-01 | Given `seed-books`, when `searchBooks(query: "dune")` is called, then title substrings match case-insensitively | integration | Exactly `B3` and `B4`, each once |
| SEARCH-02 | Given `seed-books`, when `searchBooks(query: "LE GUIN")` is called, then author name substrings match case-insensitively | integration | Exactly `B1` and `B2`, each once |
| SEARCH-03 | Given `seed-books`, when `searchBooks(query: "zzz")` is called, then no match returns an empty list | integration | `[]` with no error |
| SEARCH-04 | Given `seed-books`, when `searchBooks(query: "of")` is called, then a substring anywhere in the title matches | integration | Exactly `B1`, `B4`, and `B5`, each once |

### Validation

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| VAL-01 | Given `empty-db`, when `createBook(title: "", authorName: "Frank Herbert")` is called, then the request is rejected without writing | integration | A GraphQL error is returned; `books` returns `[]`; `authors` returns `[]` |
| VAL-02 | Given `empty-db`, when `createBook(title: "Dune")` is called with no `authorName`, then the request is rejected without writing | integration | A GraphQL error is returned (the argument is non-null in the schema); `books` returns `[]` |
| VAL-03 | Given `empty-db`, when `createReadingList(name: "")` is called, then the request is rejected without writing | integration | A GraphQL error is returned; `readingLists` returns `[]` |
| VAL-04 | Given `empty-db`, when `createReadingList` is called with the 101-character name from `long-names`, then the request is rejected without writing | integration | A GraphQL error is returned; `readingLists` returns `[]` |
| VAL-05 | Given `seed-lists` with `B1` already in `L1`, when `addBookToList(readingListId: L1, bookId: B1, position: 4)` is called, then the duplicate is rejected | integration | A GraphQL error is returned; `readingList(id: L1).items` still has exactly 3 items and `bookCount` 3 |
| VAL-06 | Given `empty-db`, when `createBook` is called once per value in `invalid-isbns`, then each request is rejected without writing | integration | Each isolated case returns a GraphQL error; `books` returns `[]` after each case |
| VAL-07 | Given `seed-books` and the empty list `L2`, when `addBookToList(readingListId: L2, bookId: B3, position: 0)` and separately `position: -1` are called, then both are rejected | integration | Each isolated case returns a GraphQL error; `readingList(id: L2).items` is `[]` and `bookCount` 0 after each |
| VAL-08 | Given `seed-books`, when `updateBook(id: B3, title: "")` is called, then the update is rejected and the book is unchanged | integration | A GraphQL error is returned; re-read `B3` still has title "Dune" |
| VAL-09 | Given `seed-books`, when `updateBook(id: B3, isbn: "12345678901")` is called, then the 11-character isbn is rejected and the book is unchanged | integration | A GraphQL error is returned; re-read `B3` still has `isbn` null |

### Integrity risks

Each row states its rationale because the tech spec has no Risks and Coverage table.

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| RISK-01 | Given `empty-db`, when `createBook(title: "Dune", authorName: "Frank Herbert", isbn: "123456789")` fails isbn validation, then no author row is left behind | integration | A GraphQL error is returned; `authors` returns `[]` and `books` returns `[]`. Rationale: `createBook` may insert a new author before validating the book, and a failure after that insert would leave an orphan author |
| RISK-02 | Given `seed-lists`, when a second `reading_list_items` row for (`L1`, `B1`) is inserted directly, then the database rejects it | db | The insert raises a unique-constraint violation; the table still holds one row for that pair. Rationale: VR-4 says the rule is enforced by both the mutation and the constraint, and each layer needs its own proof |
| RISK-03 | Given `seed-lists`, when the `books` row for `B1` is deleted directly, then its membership rows cascade and the list survives | db | Zero `reading_list_items` rows reference `B1`; the `reading_lists` row for `L1` still exists; the `B3` and `B5` rows are untouched. Rationale: F1-4 depends on `ON DELETE CASCADE` in the Data Model, and AC-05 proves it only through the API path |
| RISK-04 | Given `seed-lists`, when the `reading_lists` row for `L1` is deleted directly, then its items cascade and no `books` row is affected | db | Zero `reading_list_items` rows reference `L1`; `books` still holds 5 rows. Rationale: F2-7 depends on the same cascade in the opposite direction |

### Edge cases

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| EDGE-01 | Given `seed-books`, when `book(id)` is queried with a freshly generated UUID that matches no row, then null is returned | integration | The result is null with no error |
| EDGE-02 | Given `unread-only`, when the Books page filter "Finished" is selected, then the filtered empty state appears | e2e | Text "No books with status Finished" and a "Clear filter" link are visible; no BookCard is rendered; activating the link shows the 2 cards again |
| EDGE-03 | Given `seed-books` where `B2` has isbn "0060512759", when `createBook(title: "Copy", authorName: "Someone", isbn: "0060512759")` is called, then the duplicate isbn is rejected | integration | A GraphQL error is returned; `books` still returns 5 |
| EDGE-04 | Given `empty-db`, when `createReadingList` is called with the 100-character name from `long-names`, then the boundary value is accepted | integration | Returns the list; re-read `name` equals the 100-character string exactly |
| EDGE-05 | Given `empty-db`, when `createBook` is called once with the 10-character and once with the 13-character isbn from `valid-isbns`, then both are accepted | integration | Each isolated case returns a `Book` whose `isbn` equals the input exactly |
| EDGE-06 | Given `empty-db`, when `createBook` is called twice with `authorName: "Frank Herbert"` and different titles, then one author row is shared | integration | `authors` returns exactly one author; `author.books` for it has 2 entries; both books report the same `author.id` |
| EDGE-07 | Given `empty-db`, when the Dashboard loads, then the welcome state is shown with zero stats | e2e | A welcome message and an "Add your first book" control are visible; the stats cards read 0, 0, 0; the reading lists section is empty |
| EDGE-08 | Given `seed-lists`, when the Reading List page for `L2` loads, then the empty list state is shown | e2e | Text "This list is empty. Add some books!" and an "Add Book to List" control are visible; no item rows are rendered |
| EDGE-09 | Given `shared-book-lists` with `B3` in both `L1` and `L2`, when `removeBookFromList(readingListId: L1, bookId: B3)` is called, then only the `L1` membership is removed | integration | Returns `true`; `readingList(id: L1).items` excludes `B3`; `readingList(id: L2).items` still contains `B3` at position 1 |
| EDGE-10 | Given `seed-books`, when the Books page is viewed at viewport widths 1280, 900, and 375 pixels, then the grid uses the column counts from the design spec | e2e | At 1280px the grid has 3 or 4 columns; at 900px exactly 2; at 375px exactly 1 with full-width cards |

## Scenario Classification

All backend scenarios are planned for automation under the existing pytest gate. Browser scenarios are automated in intent but blocked by EC-04. "High" means a failure loses or corrupts data, breaks a Must-have criterion, or reports wrong counts silently.

| Scenario ID | Categories | Priority / risk | Execution mode |
|---|---|---|---|
| AC-01 | functional, persistence, contract | High | Automated |
| AC-02 | functional, persistence | Medium | Automated |
| AC-03 | functional, persistence | High | Automated |
| AC-04 | functional, persistence | Medium | Automated |
| AC-05 | functional, data integrity | High / RISK-03 | Automated |
| AC-06 | functional, contract | High | Automated |
| AC-07 | ui, empty state | Medium | Automated (blocked by EC-04) |
| AC-08 | ui, functional | High | Automated (blocked by EC-04) |
| AC-09 | functional, persistence | High | Automated |
| AC-10 | functional, persistence, ordering | High | Automated |
| AC-11 | functional, ordering, contract | High | Automated |
| AC-12 | functional, data integrity | High | Automated |
| AC-13 | functional, data integrity | High / RISK-04 | Automated |
| AC-14 | ui, ordering | High | Automated (blocked by EC-04) |
| AC-15 | ui, functional | High / GAP-04 | Automated (blocked by EC-04) |
| AC-16 | ui, navigation | Medium | Automated (blocked by EC-04) |
| SEARCH-01 | functional, contract | Medium | Automated |
| SEARCH-02 | functional, contract | Medium | Automated |
| SEARCH-03 | functional, boundary | Medium | Automated |
| SEARCH-04 | functional, contract | Medium | Automated |
| VAL-01 | validation, data integrity | High / GAP-02 | Automated |
| VAL-02 | validation, contract | Medium / GAP-02 | Automated |
| VAL-03 | validation | High / GAP-02 | Automated |
| VAL-04 | validation, boundary | High / GAP-02 | Automated |
| VAL-05 | validation, data integrity | High / RISK-02 | Automated |
| VAL-06 | validation | Medium / GAP-02 | Automated |
| VAL-07 | validation, boundary | Medium / GAP-05 | Automated |
| VAL-08 | validation, regression | Medium / GAP-02 | Automated |
| VAL-09 | validation, regression | Medium / GAP-02 | Automated |
| RISK-01 | recovery, data integrity | High | Automated |
| RISK-02 | data integrity, schema | High | Automated |
| RISK-03 | data integrity, schema | High | Automated |
| RISK-04 | data integrity, schema | High | Automated |
| EDGE-01 | contract, boundary | Medium | Automated |
| EDGE-02 | ui, empty state | Medium | Automated (blocked by EC-04) |
| EDGE-03 | validation, data integrity | Medium | Automated |
| EDGE-04 | validation, boundary | Medium | Automated |
| EDGE-05 | validation, boundary | Medium | Automated |
| EDGE-06 | functional, data integrity | Medium / GAP-06 | Automated |
| EDGE-07 | ui, empty state | Medium | Automated (blocked by EC-04) |
| EDGE-08 | ui, empty state | Medium | Automated (blocked by EC-04) |
| EDGE-09 | functional, data integrity | High | Automated |
| EDGE-10 | ui, responsive | Low | Automated (blocked by EC-04) |

Categories deliberately absent: permissions and tenant boundaries (single-user app, OOS-01), performance (OOS-07), accessibility (not specified by the design spec, OOS-09).

## Acceptance Traceability

The tech spec has no Acceptance Criteria section. Rows below are the product spec's per-feature acceptance criteria, numbered by position.

| RFC acceptance criterion | Covering scenarios |
|---|---|
| F1-1: add a book with required title and author and optional ISBN | AC-01, AC-02, EDGE-05 |
| F1-2: set reading status to want_to_read, reading, or finished | AC-01, AC-02, AC-03 |
| F1-3: edit title, author, ISBN, and status | AC-03, AC-04 |
| F1-4: delete a book and remove it from all reading lists | AC-05, RISK-03 |
| F1-5: books displayed in a grid, filterable by status | AC-06, AC-08, EDGE-02 |
| F1-6: empty state shows a call to action to add the first book | AC-07, EDGE-07 |
| F2-1: create a reading list with required name (max 100) and optional description | AC-09, VAL-03, VAL-04, EDGE-04 |
| F2-2: add any book to a reading list | AC-10 |
| F2-3: a book cannot appear in the same list twice | VAL-05, RISK-02 |
| F2-4: books in a list have a position | AC-10, AC-11, VAL-07 |
| F2-5: reorder books within a list via drag or move controls | None. GAP-01: the tech spec defines no reorder operation. See OOS-10 |
| F2-6: remove a book from a list without deleting the book | AC-12, EDGE-09 |
| F2-7: deleting a reading list does not delete its books | AC-13, RISK-04 |
| F3-1: dashboard shows total book count | AC-15, EDGE-07 |
| F3-2: dashboard shows count by status | AC-15 (reading and finished only; want-to-read blocked by GAP-04) |
| F3-3: dashboard lists reading lists with book count per list | AC-15 |
| F3-4: dashboard links to Books page and individual lists | AC-16 |

### Additional Coverage

| Source requirement / risk | Covering scenarios | Gap or deferral reference |
|---|---|---|
| VR-1: book title required, non-empty | VAL-01, VAL-08 | Whitespace-only titles: GAP-06 |
| VR-2: authorName required on create | VAL-02 | None |
| VR-3: list name required, max 100 characters | VAL-03, VAL-04, EDGE-04 | None |
| VR-4: no duplicate book in a list, enforced by constraint and mutation | VAL-05, RISK-02 | None |
| VR-5: ISBN, if provided, is 10 or 13 characters | VAL-06, VAL-09, EDGE-05 | Empty-string ISBN: GAP-06 |
| VR-6: position must be >= 1 | VAL-07 | Default and collision semantics: GAP-05 |
| Data Model: `books.isbn` UNIQUE | EDGE-03 | Error shape: GAP-02 |
| Data Model: `books.status` default `want_to_read` | AC-01 | None |
| Data Model: cascades from `books` and `reading_lists` to `reading_list_items` | RISK-03, RISK-04, AC-05, AC-13 | None |
| Data Model: `authors` reused across books (many-to-one) | EDGE-06 | Case-insensitive match: GAP-06 |
| API: `book(id)` nullable return | EDGE-01 | None |
| API: `ReadingList.bookCount` | AC-05, AC-09, AC-10, AC-11, AC-12 | None |
| Search: case-insensitive substring on title and author name | SEARCH-01 to SEARCH-04 | Wildcard escaping: GAP-03, OOS-08 |
| Product vision: search is Should-have | SEARCH-01 to SEARCH-04 | None |
| Design: Books page empty and filtered-empty states | AC-07, EDGE-02 | None |
| Design: Dashboard empty state | EDGE-07 | None |
| Design: Reading List page empty and populated states | AC-14, EDGE-08 | None |
| Design: StatusBadge labels | AC-08, AC-14 | None |
| Design: Responsive grid columns | EDGE-10 | Desktop "3 to 4 columns" is asserted as a range |
| Design: loading and error states on all three pages | None | Deferred: no frontend failure-injection harness; OOS-11 |
| Design: AddBookForm inline validation errors | None | Deferred: no field-level copy defined; OOS-12 |

## Fixtures and Test Data

### Seed books

`seed-books` loads exactly these five rows through the persistence layer and captures the generated UUIDs under the handles in the first column. Three author rows result: "Ursula K. Le Guin", "Frank Herbert", "Octavia E. Butler".

| Handle | Title | Author | Status | ISBN |
|---|---|---|---|---|
| B1 | A Wizard of Earthsea | Ursula K. Le Guin | finished | 9780547773742 |
| B2 | The Dispossessed | Ursula K. Le Guin | reading | 0060512759 |
| B3 | Dune | Frank Herbert | want_to_read | null |
| B4 | Children of Dune | Frank Herbert | want_to_read | null |
| B5 | Parable of the Sower | Octavia E. Butler | finished | null |

Derived counts used in assertions: total 5, want_to_read 2, reading 1, finished 2.

### Fixture setup and cleanup

| Fixture / data set | Used by scenarios | Setup and controlled values | Reset / cleanup |
|---|---|---|---|
| `empty-db` | AC-01, AC-02, AC-07, AC-09, VAL-01 to VAL-04, VAL-06, RISK-01, EDGE-04 to EDGE-07 | All four tables present with zero rows | Truncate all tables or roll back the test transaction after each case; each parameter case starts empty |
| `seed-books` | AC-03 to AC-06, AC-08, AC-10, SEARCH-01 to SEARCH-04, VAL-07 to VAL-09, EDGE-01, EDGE-03, EDGE-10 | The five rows above | Recreate before each test; never mutate shared handles across tests |
| `seed-lists` | AC-05, AC-11 to AC-16, VAL-05, RISK-02 to RISK-04, EDGE-08 | Requires `seed-books`. `L1` "Favorites", description "Comfort re-reads", items (B1, 1), (B3, 2), (B5, 3). `L2` "Book club", no description, no items | Recreate before each test |
| `shared-book-lists` | EDGE-09 | `seed-lists` plus (B3, 1) added to `L2` | Recreate before each test |
| `unread-only` | EDGE-02 | Only `B3` and `B4` loaded | Recreate before each test |
| `valid-isbns` | EDGE-05 | "0060512759" (10 characters), "9780547773742" (13 characters) | None; read-only constants |
| `invalid-isbns` | VAL-06 | "123456789" (9), "12345678901" (11), "12345678901234" (14). Each case uses title "Dune" and authorName "Frank Herbert" | Reset database between cases |
| `long-names` | VAL-04, EDGE-04 | A 100-character name (accepted) and a 101-character name (rejected), both built from repeated ASCII letters | None; read-only constants |

No clock control is required: no scenario asserts a timestamp value, only that `createdAt`, `updatedAt`, and `addedAt` are non-null. No random seeds are involved. All data is synthetic.

## Execution and Evidence

- **Execution mapping:** Produced when planning assigns scenario IDs to test-authoring tasks. Until then this spec has no scenario-to-selector mapping and no result may be claimed. Record the mapping alongside the feature's task files, not in this document.
- **Runner configuration:** `example/CLAUDE.md`, section `## Quality Gates`, subsection `### Backend`, entry `test: cd src/backend && python -m pytest`. No frontend `test:` entry exists (EC-04). No CI job is configured for the example.
- **Result report:** Store per-run reports under the feature's evidence location with scenario and parameter IDs, source revision (`6e87b9d` or later), application commit, database version, the actual command and selector, timestamps, outcome, and log or defect links.

An automated scenario passes only when its mapped test is discovered, executes, and its assertions pass. A green backend suite that does not include the mapped selector is not evidence for that scenario. Parameterized scenarios (VAL-06, VAL-07, EDGE-05) pass only when every listed parameter is discovered and passes. Blocked, skipped, and not-run cases are not passes.

Before implementation, each mapped test must be executed and recorded as failing on an assertion. After a fix, rerun the failed scenarios and the regression checks in the same area, keep both records, then run the full backend gate on the integrated build.

## Exit Criteria

| Gate | Required result | Enforcement |
|---|---|---|
| Test design ready | GAP-01 through GAP-06 decided and the tech spec updated; a scenario added for F2-5; this spec reviewed by the assigned owner | Human review. Not met on 2026-09-17 |
| Merge | All 34 integration and db scenarios (AC-01 to AC-06, AC-09 to AC-13, SEARCH-01 to SEARCH-04, VAL-01 to VAL-09, RISK-01 to RISK-04, EDGE-01, EDGE-03 to EDGE-06, EDGE-09) pass under the backend Quality Gates test command on the candidate build, each with a recorded red baseline | Backend `test:` gate in `CLAUDE.md`. No CI check exists yet for the example |
| Release | All merge-gate scenarios pass again on the integrated build, plus the 9 e2e scenarios (AC-07, AC-08, AC-14 to AC-16, EDGE-02, EDGE-07, EDGE-08, EDGE-10) once EC-04 is met. No open defect loses a book or list, accepts an invalid ISBN or name, or shows wrong dashboard counts | Release owner checks the evidence and open defects |
| Exception | A failed, blocked, skipped, or not-run scenario stays non-passing. Any exception names the scenario IDs, the risk, the rationale, the decision owner, and the follow-up target | Recorded with the release evidence. None granted |
| Flaky outcome | Inconsistent results are preserved and investigated; rerunning until green does not count | Test owner tracks the defect |

## Out of Scope

| Excluded behavior / category | Not applicable or deferred | Reason and risk | Decision owner / follow-up |
|---|---|---|---|
| OOS-01: accounts, authentication, multi-user isolation | Not applicable | Product spec excludes them; the app is single-user. A multi-user version needs a permissions contract and tests | Product owner, before any multi-user scope |
| OOS-02: cover images and thumbnails | Not applicable | Product spec out of scope | None |
| OOS-03: notes and annotations | Not applicable | Product spec out of scope | None |
| OOS-04: tags or categories beyond status | Not applicable | Product spec out of scope | None |
| OOS-05: ordering of `books`, `authors`, and `readingLists` results | Not applicable | Product spec excludes sorting by date; no source defines an order, so no scenario asserts one | Product owner, if a default order is wanted |
| OOS-06: sharing reading lists | Not applicable | Product spec out of scope | None |
| OOS-07: performance and load | Deferred | No workload, data volume, or latency target exists in any source | Engineering owner sets a workload contract first |
| OOS-08: `%` and `_` handling in `searchBooks` | Deferred | GAP-03. Unescaped input would let "%" match every book. A scenario is written once the tech spec states the rule | Tech spec owner |
| OOS-09: accessibility and keyboard interaction | Deferred | The design spec defines none. Not asserted rather than invented | Design owner |
| OOS-10: reordering books within a list | Deferred | GAP-01. F2-5 is a Must-have with no API. Its absence is a visible gap, not covered behavior | Tech spec owner defines the mutation; AC and VAL scenarios follow |
| OOS-11: loading and error states on pages | Deferred | Needs a frontend failure-injection harness that EC-04 does not yet provide | Frontend owner after EC-04 |
| OOS-12: AddBookForm inline validation copy | Deferred | The design spec requires inline errors but gives no text or field-level rule beyond "required" | Design owner supplies copy; e2e scenarios follow |
| OOS-13: author deletion | Not applicable | No `deleteAuthor` mutation exists; the `authors` cascade cannot be reached through the API | None |
