# Feature: Bookshelf Core

## Overview

The core bookshelf functionality: managing books and organizing them into reading lists. This is the foundation — everything the app does flows through books and lists.

## Features

### F1: Book Management

Users can add books to their bookshelf, update book details, and remove books they no longer want to track.

**Acceptance criteria:**
- User can add a book with title (required), author (required), and optional ISBN
- User can set a book's reading status: `want_to_read`, `reading`, or `finished`
- User can edit a book's title, author, ISBN, and status
- User can delete a book (removes it from all reading lists too)
- Books are displayed in a grid, filterable by status
- Empty state shows a clear call-to-action to add the first book

### F2: Reading Lists

Users can create named reading lists and add books to them in a specific order.

**Acceptance criteria:**
- User can create a reading list with a name (required, max 100 chars) and optional description
- User can add any book to a reading list
- A book cannot appear in the same reading list twice
- Books in a list have a position (order matters)
- User can reorder books within a list via drag or move controls
- User can remove a book from a list without deleting the book itself
- Deleting a reading list does not delete the books in it

### F3: Dashboard

A landing page showing reading stats and quick access to lists.

**Acceptance criteria:**
- Shows total book count
- Shows count by status (want to read, reading, finished)
- Shows list of reading lists with book count per list
- Links to Books page and individual reading lists

## Out of scope

- User accounts or authentication (single-user app)
- Book cover images or thumbnails
- Notes or annotations on books
- Tags or categories beyond reading status
- Sorting books by date added or date finished
- Sharing reading lists with others
