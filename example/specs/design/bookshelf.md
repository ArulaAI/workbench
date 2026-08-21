# Design Spec: Bookshelf Core

## Pages

### Dashboard (`/`)

The landing page. Shows reading stats at a glance and links to deeper views.

**Layout:**
- Header: App name ("Bookshelf")
- Stats row: 3 cards showing total books, currently reading, finished
- Reading lists section: list of reading lists with book count, links to detail view
- Quick action: "Add a book" button

**States:**
- **Empty:** No books yet. Show a welcome message and prominent "Add your first book" CTA.
- **Populated:** Stats cards show real numbers. Reading lists section shows list names with counts.
- **Loading:** Skeleton cards in stats row, skeleton list items below.
- **Error:** Inline error message with retry button.

### Books Page (`/books`)

All books in a filterable grid.

**Layout:**
- Page title: "Books"
- Filter bar: status filter tabs (All, Want to Read, Reading, Finished) with counts
- Book grid: responsive grid of BookCard components
- Add button: floating or fixed "Add Book" button that opens AddBookForm

**States:**
- **Empty (no books at all):** Illustration + "Your bookshelf is empty" + Add Book CTA.
- **Empty (filtered):** "No books with status X" message. Clear filter link.
- **Populated:** Grid of BookCards. Active filter tab highlighted.
- **Loading:** Skeleton grid of 6 placeholder cards.
- **Error:** Inline error with retry.

### Reading List Page (`/lists/:id`)

A single reading list with ordered books.

**Layout:**
- Back link to Dashboard
- List name as page title, description below (if present)
- Ordered list of books (numbered or draggable)
- "Add book to list" action
- Each item shows book title, author, status badge, remove button

**States:**
- **Empty:** "This list is empty. Add some books!" + Add Book to List CTA.
- **Populated:** Numbered list of books with status badges and remove buttons.
- **Loading:** Skeleton list of 4 items.
- **Error:** Inline error with retry.

## Components

### BookCard

Displays a single book in the grid.

- Title (primary text, bold)
- Author name (secondary text)
- StatusBadge
- Click to edit (opens edit form or navigates to detail)

### ReadingListCard

Displays a reading list on the dashboard.

- List name (primary text)
- Book count ("12 books")
- Description preview (first line, truncated)
- Click navigates to Reading List Page

### StatusBadge

Colored badge showing reading status.

- `want_to_read` → neutral/default style, label "Want to Read"
- `reading` → in-progress style (amber/warm), label "Reading"
- `finished` → success style (green), label "Finished"

### AddBookForm

Form for creating or editing a book.

- Title input (required)
- Author input (required, text — creates author if new)
- ISBN input (optional)
- Status select (default: "Want to Read")
- Submit and Cancel buttons
- Validation: show inline errors for required fields

## Responsive Behavior

- **Desktop (≥1024px):** Book grid shows 3-4 columns
- **Tablet (768-1023px):** Book grid shows 2 columns
- **Mobile (<768px):** Book grid shows 1 column, full-width cards
