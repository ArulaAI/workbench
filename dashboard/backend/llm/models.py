"""Pydantic response models for structured LLM output.

Each model defines the schema that instructor validates and retries against.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AmbiguityIssue(BaseModel):
    """A single ambiguity found in an acceptance criterion."""
    criterion_text: str = Field(description="The acceptance criterion being analyzed")
    missing_condition: str = Field(description="What boundary condition or edge case is missing")
    severity: str = Field(description="critical, major, or minor")
    suggested_clause: str = Field(description="Concrete text to add that resolves the ambiguity")


class AmbiguityReport(BaseModel):
    """Analysis of acceptance criteria for missing boundary conditions."""
    issues: list[AmbiguityIssue] = Field(default_factory=list)
    summary: str = Field(description="One-sentence summary of the spec's criteria quality")


class FixSuggestion(BaseModel):
    """A concrete text edit that resolves a detected spec issue."""
    section: str = Field(description="Which spec section this fix applies to")
    issue: str = Field(description="What problem this fix addresses")
    old_text: str = Field(description="The existing text to replace (exact match)")
    new_text: str = Field(description="The replacement text")
    rationale: str = Field(description="Why this change improves the spec")
    severity: str = Field(description="critical, major, minor, or style")


class UserPersona(BaseModel):
    """A user persona for the spec."""
    name: str = Field(description="Short persona label (e.g., 'Engineering Lead')")
    problem: str = Field(description="What this persona struggles with, framed as their pain")


class UserStory(BaseModel):
    """A user story in Given/When/Then format."""
    id: str = Field(description="Story ID (e.g., S1, S2)")
    story: str = Field(description="As a {persona}, I want to {action}, so that {outcome}")
    acceptance_criteria: str = Field(description="Given... When... Then... format")
    priority: str = Field(description="Must, Should, or Could")


class IntentScope(BaseModel):
    """LLM-identified codebase areas relevant to an author's intent."""
    keywords: list[str] = Field(description="Technical keywords and terms to search for in the codebase (function names, class names, module names, file patterns)")
    concepts: list[str] = Field(description="Higher-level concepts the intent relates to (e.g., 'authentication', 'query validation', 'database migration')")
    reasoning: str = Field(description="Brief explanation of why these areas are relevant")


class SeedFiles(BaseModel):
    """File paths directly relevant to implementing a feature, selected by an LLM from the full project file list."""
    seeds: list[str] = Field(description="File paths that are direct integration points, pattern references, data sources, or core infrastructure for this feature")
    reasoning: str = Field(description="Brief explanation of the selection rationale")


class SpecDraft(BaseModel):
    """A complete spec draft generated from a problem statement."""
    problem: str = Field(description="2-3 sentences describing the user pain")
    users: list[UserPersona] = Field(description="Affected user personas")
    stories: list[UserStory] = Field(description="User stories with acceptance criteria")
    scope_in: list[str] = Field(description="What is in scope")
    scope_out: list[str] = Field(description="What is out of scope, each with a reason")
    success_criteria: list[str] = Field(description="Measurable outcomes with thresholds")
