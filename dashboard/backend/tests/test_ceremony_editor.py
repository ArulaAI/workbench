"""Tests for the Define Ceremony Editor: draft generation, validation, and resolver.

Covers template conformance, structural checks, cross-spec validation,
codebase reference checks, sizing heuristics, vision alignment,
draft persistence, and GraphQL schema integration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from backend.ceremony_generator import (
    _check_required_sections,
    _serialize_context,
    generate_spec_draft,
    load_spec_draft,
    save_spec_draft,
)
from backend.ceremony_validator import (
    _validate_codebase,
    _validate_cross_spec,
    _validate_sizing,
    _validate_structure,
    _validate_template,
    _validate_vision,
    load_validation_state,
    save_validation_state,
    validate_spec,
)
from backend.resolvers.ceremony_editor import (
    get_spec_draft,
    get_validation_state,
    update_draft,
)
from backend.resolvers.ceremony_types import (
    CeremonyState,
    CeremonyStatus,
    ContextPackage,
    CodebaseItem,
    LearningItem,
    DefectItem,
    KnowledgeItem,
    RelatedFeature,
    AuditHistoryItem,
    Revision,
    SpecDraft,
    ValidationState,
    _save_ceremony_state,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project structure for testing."""
    (tmp_path / ".speed" / "features").mkdir(parents=True)
    (tmp_path / ".speed" / "context").mkdir(parents=True)
    (tmp_path / "templates").mkdir(parents=True)
    (tmp_path / "specs" / "product").mkdir(parents=True)
    (tmp_path / "specs" / "tech").mkdir(parents=True)
    (tmp_path / "specs" / "design").mkdir(parents=True)

    # Write minimal templates
    (tmp_path / "templates" / "prd.md").write_text(
        "# F{n}: {Feature Name}\n\n"
        "## Problem\n\n## Users\n\n## User Stories\n"
        "| ID | Story | Acceptance Criteria | Priority |\n"
        "|----|-------|---------------------|----------|\n\n"
        "## User Flows\n\n## Success Criteria\n\n"
        "## Scope\n### In Scope\n### Out of Scope (and why)\n"
    )
    (tmp_path / "templates" / "rfc.md").write_text(
        "# RFC: {Feature Name}\n\n"
        "## Basic Example\n\n## Interface Contract\n"
        "### Consumes\n### Produces\n\n"
        "## Data Model\n\n## API Surface\n\n"
        "## Testing\n\n## Key Decisions\n"
    )
    (tmp_path / "templates" / "design.md").write_text(
        "# Design: {Feature Name}\n\n"
        "## Design Intent\n\n## Layout Structure\n\n"
        "## Component Inventory\n\n## States\n\n"
        "## Data Binding\n\n## Typography\n"
    )
    return tmp_path


@pytest.fixture
def sample_context() -> ContextPackage:
    """Minimal context package for testing."""
    return ContextPackage(
        intent="Build a user authentication system",
        feature_name="user-auth",
        scoped_area=["src/auth.py", "src/models/user.py"],
        codebase=[
            CodebaseItem(path="src/auth.py", description="function authenticate", node_ids=["n1"]),
        ],
        learnings=[
            LearningItem(text="JWT tokens should expire after 1 hour", source_feature="session-mgmt", confidence="high"),
        ],
        defects=[
            DefectItem(name="Token refresh race condition", severity="major", status="open", related_files=["src/auth.py"]),
        ],
        project_knowledge=[
            KnowledgeItem(text="Use argon2 for password hashing", confidence="high", source="convention"),
        ],
        vision_status="available",
        vision_content="A secure, privacy-first platform for team collaboration.",
        related_features=[
            RelatedFeature(name="session-mgmt", state="ratified", overlap_files=["src/auth.py"]),
        ],
        audit_history=[],
        assembled_at="2026-01-01T00:00:00Z",
        sources_status={"codebase": "ok", "learnings": "ok"},
    )


@pytest.fixture
def sample_draft() -> SpecDraft:
    """A valid PRD draft with all required sections."""
    return SpecDraft(
        feature_name="user-auth",
        spec_type="prd",
        content=(
            "# F1: User Auth\n\n"
            "## Problem\nUsers cannot log in securely.\n\n"
            "## Users\nTeam members who need access.\n\n"
            "## User Stories\n"
            "| ID | Story | Acceptance Criteria | Priority |\n"
            "|----|-------|---------------------|----------|\n"
            "| S1 | As a user, I want to log in | Given valid creds When I submit Then I'm authenticated | Must |\n"
            "| S2 | As a user, I want to log out | Given I'm logged in When I click logout Then session ends | Must |\n\n"
            "## User Flows\nS1: Login flow starts at /login.\n\n"
            "## Success Criteria\n- [ ] Login completes in < 2s\n\n"
            "## Scope\n### In Scope\n- Login, logout\n"
            "### Out of Scope (and why)\n- SSO (requires enterprise license)\n"
        ),
        file_path="specs/product/user-auth.md",
        template_name="prd.md",
        generated_at="2026-01-01T00:00:00Z",
        child_specs=[],
    )


def _setup_ceremony(
    tmp_path: Path,
    feature_name: str = "user-auth",
    *,
    claim_prd: bool = True,
) -> None:
    """Create ceremony.json plus an auto-claimed PRD so edit checks pass.

    Mirrors what `declareIntent` does in production: ceremony.json is
    written and `claim-prd.json` is written for the ceremony author.
    Pass `claim_prd=False` to test the unclaimed edit path.
    """
    from backend.resolvers.ceremony_types import ReflogEntry, SpecClaim, save_spec_claim
    from backend.paths import get_paths

    ceremony_dir = tmp_path / ".speed" / "features" / feature_name
    ceremony_dir.mkdir(parents=True, exist_ok=True)
    state = CeremonyState(
        feature_name=feature_name,
        author="test",
        author_email="test@local",
        created_at="2026-01-01T00:00:00Z",
        is_multiplayer=False,
        current_revision="r1",
        revision_count=1,
        revisions={
            "r1": Revision(
                revision_id="r1",
                parent_id=None,
                status=CeremonyStatus.DRAFTING,
                spec_content_hash="0" * 64,
                context_package_hash="0" * 64,
                validation_hash="0" * 64,
                created_at="2026-01-01T00:00:00Z",
                reason="initial",
            )
        },
        reflog=[
            ReflogEntry(
                from_revision=None,
                to_revision="r1",
                at="2026-01-01T00:00:00Z",
                actor="test",
                actor_email="test@local",
                reason="initial",
            )
        ],
    )
    _save_ceremony_state(ceremony_dir / "ceremony.json", state)

    if claim_prd:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        paths = get_paths(tmp_path)
        save_spec_claim(
            paths.ceremony_claim(feature_name, "prd"),
            SpecClaim(
                spec_type="prd",
                claimant="test",
                claimant_email="test@local",
                claimed_at=now_iso,
                last_activity_at=now_iso,
                released_at=None,
            ),
        )


# ════════════════════════════════════════════════════════════════
# Generator tests
# ════════════════════════════════════════════════════════════════


class TestRequiredSections:
    def test_prd_all_present(self):
        content = "## Problem\n\n## Users\n\n## User Stories\n\n## Scope\n### In Scope\n"
        assert _check_required_sections(content, "prd") == []

    def test_prd_missing_problem(self):
        content = "## Users\n\n## User Stories\n\n## Scope\n"
        missing = _check_required_sections(content, "prd")
        assert "Problem" in missing

    def test_rfc_missing_data_model(self):
        content = "## Basic Example\n\n## Interface Contract\n\n## API Surface\n"
        missing = _check_required_sections(content, "rfc")
        assert "Data Model" in missing

    def test_design_all_present(self):
        content = "## Design Intent\n\n## Layout Structure\n\n## Component Inventory\n\n## States\n"
        assert _check_required_sections(content, "design") == []


class TestContextSerialization:
    def test_serializes_intent_and_feature(self, sample_context):
        text = _serialize_context(sample_context)
        assert "user-auth" in text
        assert "user authentication" in text

    def test_includes_defects(self, sample_context):
        text = _serialize_context(sample_context)
        assert "Token refresh race condition" in text

    def test_includes_learnings(self, sample_context):
        text = _serialize_context(sample_context)
        assert "JWT tokens" in text


class TestDraftGeneration:
    def test_generate_calls_llm(self, tmp_project, sample_context):
        complete_prd = (
            "# F1: User Auth\n\n"
            "## Problem\nUsers can't log in.\n\n"
            "## Users\nTeam members.\n\n"
            "## User Stories\n| ID | Story | Criteria | Priority |\n"
            "|----|-------|----------|----------|\n"
            "| S1 | Login | Given... | Must |\n\n"
            "## Scope\n### In Scope\n- Login\n"
        )
        with patch("backend.llm.llm_complete_text", return_value=complete_prd):
            draft = generate_spec_draft(
                intent="Build auth",
                context_package=sample_context,
                spec_type="prd",
                model="test/model",
                project_root=tmp_project,
            )
        assert draft.spec_type == "prd"
        assert draft.feature_name == "user-auth"
        assert "Problem" in draft.content

    def test_retries_on_missing_sections(self, tmp_project, sample_context):
        incomplete = "## Problem\nStuff.\n\n## Users\nPeople.\n"
        complete = (
            incomplete
            + "## User Stories\n| ID |\n|-|\n| S1 |\n\n"
            + "## Scope\n### In Scope\n- Auth\n"
        )
        call_count = 0

        def mock_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return incomplete if call_count == 1 else complete

        with patch("backend.llm.llm_complete_text", side_effect=mock_llm):
            draft = generate_spec_draft(
                intent="Build auth",
                context_package=sample_context,
                spec_type="prd",
                model="test/model",
                project_root=tmp_project,
            )
        assert call_count == 2
        assert "User Stories" in draft.content

    def test_strips_code_fences(self, tmp_project, sample_context):
        fenced = "```markdown\n## Problem\n## Users\n## User Stories\n## Scope\n```"
        with patch("backend.llm.llm_complete_text", return_value=fenced):
            draft = generate_spec_draft(
                intent="Build auth",
                context_package=sample_context,
                spec_type="prd",
                model="test/model",
                project_root=tmp_project,
            )
        assert not draft.content.startswith("```")

    def test_invalid_spec_type(self, tmp_project, sample_context):
        with pytest.raises(ValueError, match="Unknown spec_type"):
            generate_spec_draft(
                intent="x", context_package=sample_context,
                spec_type="invalid", model="m",
                project_root=tmp_project,
            )


class TestDraftPersistence:
    def test_save_and_load(self, tmp_project, sample_draft):
        _setup_ceremony(tmp_project)
        save_spec_draft(tmp_project, "user-auth", sample_draft)
        loaded = load_spec_draft(tmp_project, "user-auth")
        assert loaded is not None
        assert loaded.feature_name == "user-auth"
        assert loaded.content == sample_draft.content
        assert loaded.spec_type == "prd"

    def test_load_nonexistent(self, tmp_project):
        assert load_spec_draft(tmp_project, "nope") is None


# ════════════════════════════════════════════════════════════════
# Validator tests
# ════════════════════════════════════════════════════════════════


class TestTemplateDimension:
    def test_all_sections_present(self, tmp_project, sample_draft):
        dim = _validate_template(sample_draft, tmp_project)
        assert dim.name == "template"
        assert dim.tier == 1
        errors = [i for i in dim.issues if i.severity == "error"]
        assert len(errors) == 0

    def test_missing_required_section(self, tmp_project):
        draft = SpecDraft(
            feature_name="x", spec_type="prd",
            content="## Users\n\n## User Stories\n\n## Scope\n",
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_template(draft, tmp_project)
        assert dim.status == "fail"
        missing_msgs = [i.message for i in dim.issues if i.severity == "error"]
        assert any("Problem" in m for m in missing_msgs)

    def test_placeholder_table_warning(self, tmp_project):
        draft = SpecDraft(
            feature_name="x", spec_type="prd",
            content=(
                "## Problem\n\n## Users\n\n## User Stories\n"
                "| ID | Story |\n|----|-------|\n| TBD | ... |\n\n## Scope\n"
            ),
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_template(draft, tmp_project)
        warnings = [i for i in dim.issues if i.severity == "warning"]
        assert any("placeholder" in i.message.lower() for i in warnings)


class TestStructureDimension:
    def test_given_when_then_present(self, tmp_project, sample_draft):
        dim = _validate_structure(sample_draft, tmp_project)
        assert dim.name == "structure"
        gwt_issues = [i for i in dim.issues if "Given/When/Then" in i.message]
        assert len(gwt_issues) == 0

    def test_missing_gwt(self, tmp_project):
        draft = SpecDraft(
            feature_name="x", spec_type="prd",
            content=(
                "## User Stories\n"
                "| ID | Story | Acceptance Criteria | Priority |\n"
                "|----|-------|---------------------|----------|\n"
                "| S1 | Login | User logs in | Must |\n"
            ),
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_structure(draft, tmp_project)
        gwt_issues = [i for i in dim.issues if "Given/When/Then" in i.message]
        assert len(gwt_issues) > 0

    def test_missing_story_ids(self, tmp_project):
        draft = SpecDraft(
            feature_name="x", spec_type="prd",
            content=(
                "## User Stories\n"
                "| ID | Story | Criteria | Priority |\n"
                "|----|-------|----------|----------|\n"
                "| | Login | Given... | Must |\n"
            ),
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_structure(draft, tmp_project)
        id_issues = [i for i in dim.issues if "S-prefixed" in i.message]
        assert len(id_issues) > 0

    def test_scope_subsections(self, tmp_project):
        draft = SpecDraft(
            feature_name="x", spec_type="prd",
            content="## Scope\nJust some text.\n",
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_structure(draft, tmp_project)
        scope_issues = [i for i in dim.issues if "In Scope" in i.message or "Out of Scope" in i.message]
        assert len(scope_issues) == 2


class TestCrossSpecDimension:
    def test_no_companions_passes(self, tmp_project, sample_draft):
        dim = _validate_cross_spec(sample_draft, tmp_project)
        assert dim.status == "pass"

    def test_coverage_gap_detected(self, tmp_project):
        # Create a PRD with stories S1, S2, S3
        prd = SpecDraft(
            feature_name="x", spec_type="prd",
            content=(
                "> See [rfc](../tech/x.md) for tech context.\n\n"
                "## User Stories\n"
                "| ID | Story |\n|----|-------|\n"
                "| S1 | Login |\n| S2 | Logout |\n| S3 | Reset |\n"
            ),
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        # Create companion RFC referencing only S1, S2
        rfc_path = tmp_project / "specs" / "tech" / "x.md"
        rfc_path.write_text("# RFC\n\nCovers S1 and S2.\n")

        dim = _validate_cross_spec(prd, tmp_project)
        gap_issues = [i for i in dim.issues if "S3" in i.message]
        assert len(gap_issues) > 0


class TestCodebaseDimension:
    def test_existing_file_passes(self, tmp_project):
        (tmp_project / "src").mkdir()
        (tmp_project / "src" / "auth.py").write_text("# auth")
        draft = SpecDraft(
            feature_name="x", spec_type="rfc",
            content="References `src/auth.py` for authentication.\n",
            file_path="specs/tech/x.md", template_name="rfc.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_codebase(draft, tmp_project)
        assert all(i.severity != "warning" for i in dim.issues)

    def test_missing_reference_flagged(self, tmp_project):
        draft = SpecDraft(
            feature_name="x", spec_type="rfc",
            content="References `src/nonexistent/handler.py` for the API.\n",
            file_path="specs/tech/x.md", template_name="rfc.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_codebase(draft, tmp_project)
        assert len(dim.issues) > 0
        assert any("not found" in i.message for i in dim.issues)

    def test_no_references_passes(self, tmp_project):
        draft = SpecDraft(
            feature_name="x", spec_type="rfc",
            content="No backtick file references here.\n",
            file_path="specs/tech/x.md", template_name="rfc.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_codebase(draft, tmp_project)
        assert dim.status == "pass"


class TestSizingDimension:
    def test_small_spec_passes(self, tmp_project, sample_draft):
        dim = _validate_sizing(sample_draft, tmp_project)
        assert dim.status == "pass"

    def test_large_spec_warns(self, tmp_project):
        stories = "\n".join(f"| S{i} | Story {i} | Given... | Must |" for i in range(1, 9))
        draft = SpecDraft(
            feature_name="x", spec_type="prd",
            content=(
                "## User Stories\n"
                "| ID | Story | Criteria | Priority |\n"
                "|----|-------|----------|----------|\n"
                + stories + "\n\n"
                "## API Surface\n"
                "mutation createUser\nmutation updateUser\nmutation deleteUser\n"
            ),
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_sizing(draft, tmp_project)
        assert dim.status in ("warn", "fail")
        assert any("decompos" in i.message.lower() for i in dim.issues)


class TestVisionDimension:
    def test_missing_vision_warns(self, tmp_project):
        draft = SpecDraft(
            feature_name="x", spec_type="prd",
            content="## Problem\nStuff.\n",
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_vision(draft, tmp_project)
        assert dim.status == "warn"
        assert any("missing" in i.message.lower() for i in dim.issues)

    def test_available_vision_no_model_passes(self, tmp_project):
        """With vision available but no model, no LLM check runs."""
        feat_dir = tmp_project / ".speed" / "features" / "x"
        feat_dir.mkdir(parents=True)
        (feat_dir / "context-package.json").write_text(json.dumps({
            "vision_status": "available",
            "vision_content": "A great product.",
        }))
        draft = SpecDraft(
            feature_name="x", spec_type="prd",
            content="## Problem\nAligned with vision.\n",
            file_path="specs/product/x.md", template_name="prd.md",
            generated_at=None, child_specs=[],
        )
        dim = _validate_vision(draft, tmp_project, model=None)
        # Without a model, no LLM check -- should pass with no issues
        assert dim.status == "pass"


class TestValidateSpec:
    def test_all_six_dimensions(self, tmp_project, sample_draft):
        vs = validate_spec(sample_draft, tmp_project)
        assert isinstance(vs, ValidationState)
        dim_names = {d.name for d in vs.dimensions}
        assert dim_names == {"template", "structure", "cross_spec", "codebase", "sizing", "vision"}

    def test_tier_filter_tier1_only(self, tmp_project, sample_draft):
        vs = validate_spec(sample_draft, tmp_project, tiers=[1])
        dim_names = {d.name for d in vs.dimensions}
        assert dim_names == {"template", "structure"}

    def test_tier_filter_tier2_only(self, tmp_project, sample_draft):
        vs = validate_spec(sample_draft, tmp_project, tiers=[2])
        dim_names = {d.name for d in vs.dimensions}
        assert dim_names == {"cross_spec", "codebase", "sizing", "vision"}

    def test_counts_correct(self, tmp_project, sample_draft):
        vs = validate_spec(sample_draft, tmp_project)
        total = vs.pass_count + vs.warn_count + vs.fail_count
        assert total == len(vs.dimensions)


class TestValidationPersistence:
    def test_save_and_load(self, tmp_project, sample_draft):
        _setup_ceremony(tmp_project)
        vs = validate_spec(sample_draft, tmp_project)
        save_validation_state(tmp_project, "user-auth", vs)
        loaded = load_validation_state(tmp_project, "user-auth")
        assert loaded is not None
        assert len(loaded.dimensions) == len(vs.dimensions)
        assert loaded.pass_count == vs.pass_count

    def test_load_nonexistent(self, tmp_project):
        assert load_validation_state(tmp_project, "nope") is None


# ════════════════════════════════════════════════════════════════
# Resolver tests
# ════════════════════════════════════════════════════════════════


class TestResolverQueries:
    def test_get_spec_draft_not_found(self, tmp_project):
        assert get_spec_draft(tmp_project, "nonexistent") is None

    def test_get_validation_state_not_found(self, tmp_project):
        assert get_validation_state(tmp_project, "nonexistent") is None

    def test_get_spec_draft_returns_persisted(self, tmp_project, sample_draft):
        _setup_ceremony(tmp_project)
        save_spec_draft(tmp_project, "user-auth", sample_draft)
        result = get_spec_draft(tmp_project, "user-auth")
        assert result is not None
        assert result.feature_name == "user-auth"


class TestUpdateDraft:
    def test_update_saves_new_content(self, tmp_project, sample_draft):
        _setup_ceremony(tmp_project)
        save_spec_draft(tmp_project, "user-auth", sample_draft)

        with patch("backend.resolvers.ceremony_editor.get_current_actor", return_value=("test", "test@local")), \
             patch("backend.resolvers.ceremony_authz.get_current_actor", return_value=("test", "test@local")), \
             patch("backend.resolvers.ceremony_claims.get_current_actor", return_value=("test", "test@local")), \
             patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("test", "test@local")):
            updated = update_draft(tmp_project, "user-auth", "prd", "## Problem\nNew content.\n")

        assert updated.content == "## Problem\nNew content.\n"
        loaded = load_spec_draft(tmp_project, "user-auth", "prd")
        assert loaded is not None
        assert "New content" in loaded.content

    def test_update_no_draft_raises(self, tmp_project):
        _setup_ceremony(tmp_project)
        with patch("backend.resolvers.ceremony_editor.get_current_actor", return_value=("test", "test@local")), \
             patch("backend.resolvers.ceremony_authz.get_current_actor", return_value=("test", "test@local")), \
             patch("backend.resolvers.ceremony_claims.get_current_actor", return_value=("test", "test@local")), \
             patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("test", "test@local")):
            with pytest.raises(FileNotFoundError):
                update_draft(tmp_project, "user-auth", "prd", "content")

    def test_update_wrong_author_raises(self, tmp_project, sample_draft):
        _setup_ceremony(tmp_project)
        save_spec_draft(tmp_project, "user-auth", sample_draft)

        with patch("backend.resolvers.ceremony_editor.get_current_actor", return_value=("other", "other@local")), \
             patch("backend.resolvers.ceremony_authz.get_current_actor", return_value=("other", "other@local")), \
             patch("backend.resolvers.ceremony_claims.get_current_actor", return_value=("other", "other@local")), \
             patch("backend.resolvers.ceremony_types.get_current_actor", return_value=("other", "other@local")):
            with pytest.raises(PermissionError):
                update_draft(tmp_project, "user-auth", "prd", "hijack")
