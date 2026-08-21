# Tech Spec: Bookshelf Core

## Data Model

### Tables

#### `authors`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default gen_random_uuid() |
| name | VARCHAR(255) | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL, default now() |

#### `books`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default gen_random_uuid() |
| title | VARCHAR(255) | NOT NULL |
| isbn | VARCHAR(13) | NULLABLE, UNIQUE |
| status | ENUM('want_to_read', 'reading', 'finished') | NOT NULL, default 'want_to_read' |
| author_id | UUID | NOT NULL, FK → authors(id) ON DELETE CASCADE |
| created_at | TIMESTAMPTZ | NOT NULL, default now() |
| updated_at | TIMESTAMPTZ | NOT NULL, default now() |

#### `reading_lists`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default gen_random_uuid() |
| name | VARCHAR(100) | NOT NULL |
| description | TEXT | NULLABLE |
| created_at | TIMESTAMPTZ | NOT NULL, default now() |

#### `reading_list_items`

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default gen_random_uuid() |
| reading_list_id | UUID | NOT NULL, FK → reading_lists(id) ON DELETE CASCADE |
| book_id | UUID | NOT NULL, FK → books(id) ON DELETE CASCADE |
| position | INTEGER | NOT NULL |
| added_at | TIMESTAMPTZ | NOT NULL, default now() |
| | | UNIQUE(reading_list_id, book_id) |

### Relationships

- `books.author_id` → `authors.id` (many-to-one)
- `reading_list_items.reading_list_id` → `reading_lists.id` (many-to-one)
- `reading_list_items.book_id` → `books.id` (many-to-one)
- `reading_list_items` is a join table: `reading_lists` ↔ `books` (many-to-many)

## GraphQL API

### Queries

| Query | Arguments | Returns |
|-------|-----------|---------|
| `books` | `status: BookStatus` (optional filter) | `[Book!]!` |
| `book` | `id: ID!` | `Book` |
| `authors` | — | `[Author!]!` |
| `readingLists` | — | `[ReadingList!]!` |
| `readingList` | `id: ID!` | `ReadingList` |
| `searchBooks` | `query: String!` | `[Book!]!` |

### Mutations

| Mutation | Arguments | Returns |
|----------|-----------|---------|
| `createBook` | `title: String!, authorName: String!, isbn: String, status: BookStatus` | `Book!` |
| `updateBook` | `id: ID!, title: String, authorName: String, isbn: String, status: BookStatus` | `Book!` |
| `deleteBook` | `id: ID!` | `Boolean!` |
| `createReadingList` | `name: String!, description: String` | `ReadingList!` |
| `deleteReadingList` | `id: ID!` | `Boolean!` |
| `addBookToList` | `readingListId: ID!, bookId: ID!, position: Int` | `ReadingListItem!` |
| `removeBookFromList` | `readingListId: ID!, bookId: ID!` | `Boolean!` |

### Types

```graphql
enum BookStatus {
  WANT_TO_READ
  READING
  FINISHED
}

type Author {
  id: ID!
  name: String!
  books: [Book!]!
}

type Book {
  id: ID!
  title: String!
  isbn: String
  status: BookStatus!
  author: Author!
  createdAt: DateTime!
  updatedAt: DateTime!
}

type ReadingList {
  id: ID!
  name: String!
  description: String
  items: [ReadingListItem!]!
  bookCount: Int!
}

type ReadingListItem {
  id: ID!
  book: Book!
  position: Int!
  addedAt: DateTime!
}
```

## Validation Rules

- Book title is required (non-empty string)
- Book must have an author (authorName required on create)
- Reading list name is required, max 100 characters
- A book cannot appear in the same reading list twice (enforced by DB unique constraint + mutation check)
- ISBN, if provided, must be 10 or 13 characters
- Position in reading list must be >= 1

## Search

`searchBooks` performs case-insensitive substring matching on `books.title` and `authors.name`. No full-text search engine — use SQL `ILIKE`.
