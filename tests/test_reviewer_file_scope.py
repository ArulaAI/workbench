#!/usr/bin/env python3
"""Tests for Task File Scope section in assemble_reviewer().

Verifies that Change A (reviewer merge conflict fix) correctly renders
the files_touched list into the reviewer prompt, enabling the reviewer
to distinguish in-scope files from out-of-scope files.
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lib"))

from lib.context.assembly import assemble_reviewer


# ── Fixtures ──────────────────────────────────────────────────────────

MINIMAL_TASK_CONTEXT = {"upstream": [], "downstream": []}
MINIMAL_SPEC_CONTEXT = {"relevant_sections": []}

TASK_WITH_FILES = {
    "id": "3",
    "title": "Package page inquiry integration",
    "description": "Wire up inquiry form on package page",
    "acceptance_criteria": [],
    "files_touched": [
        "travel-web/app/packages/[slug]/page.tsx",
        "travel-web/__tests__/components/inquiry/handle-inquiry.test.tsx",
        "travel-web/__tests__/components/inquiry/conversation-lifecycle.test.tsx",
    ],
}

TASK_EMPTY_FILES = {
    "id": "2",
    "title": "Inquiry form component",
    "description": "Build the inquiry form",
    "acceptance_criteria": [],
    "files_touched": [],
}

TASK_NO_FILES_KEY = {
    "id": "1",
    "title": "WhatsApp link component",
    "description": "Build WhatsApp deep link utility",
    "acceptance_criteria": [],
}

DIFF = "diff --git a/travel-web/app/packages/[slug]/page.tsx\n+import { WhatsAppLink } from '../inquiry'\n"


# ── Tests ─────────────────────────────────────────────────────────────


class TestReviewerFileScope:
    """Verify the Task File Scope section in reviewer prompt output."""

    def test_files_touched_present_renders_section(self):
        result = assemble_reviewer(
            task=TASK_WITH_FILES,
            diff=DIFF,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        assert "### Task File Scope" in result

    def test_files_touched_present_renders_all_files(self):
        result = assemble_reviewer(
            task=TASK_WITH_FILES,
            diff=DIFF,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        for f in TASK_WITH_FILES["files_touched"]:
            assert f"`{f}`" in result, f"Expected file {f} in reviewer prompt"

    def test_out_of_scope_instruction_present(self):
        result = assemble_reviewer(
            task=TASK_WITH_FILES,
            diff=DIFF,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        assert "out_of_scope" in result
        assert "not `issues`" in result or "not `issues`:" in result

    def test_empty_files_touched_no_section(self):
        result = assemble_reviewer(
            task=TASK_EMPTY_FILES,
            diff=DIFF,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        assert "### Task File Scope" not in result

    def test_missing_files_touched_key_no_section(self):
        result = assemble_reviewer(
            task=TASK_NO_FILES_KEY,
            diff=DIFF,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        assert "### Task File Scope" not in result

    def test_section_appears_before_git_diff(self):
        result = assemble_reviewer(
            task=TASK_WITH_FILES,
            diff=DIFF,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        scope_pos = result.find("### Task File Scope")
        diff_pos = result.find("### Git Diff")
        assert scope_pos != -1, "Task File Scope section not found"
        assert diff_pos != -1, "Git Diff section not found"
        assert scope_pos < diff_pos, (
            "Task File Scope should appear before Git Diff"
        )

    def test_single_file_renders_correctly(self):
        task = {
            "id": "5",
            "title": "Single file task",
            "description": "One file only",
            "acceptance_criteria": [],
            "files_touched": ["src/index.ts"],
        }
        result = assemble_reviewer(
            task=task,
            diff=DIFF,
            task_context=MINIMAL_TASK_CONTEXT,
            spec_context=MINIMAL_SPEC_CONTEXT,
        )
        assert "### Task File Scope" in result
        assert "`src/index.ts`" in result
