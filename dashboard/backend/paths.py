"""Path resolution for single-player and multiplayer SPEED layouts.

Single-player:
  .speed/features/{name}/        everything (tasks, logs, state, contracts)
  .speed/memory/                 observations, conventions
  .speed/defects/                defect state
  .speed/context/                CSG, skeletons, alignment
  .speed/active_feature          active feature marker
  .speed/dashboard.db            SQLite cache

Multiplayer (after speed mp-init):
  .speed/shared/features/{name}/ tasks, contracts, spec_path (git-tracked)
  .speed/local/features/{name}/  logs, state.json, running/, support/ (gitignored)
  .speed/shared/knowledge/       observations, conventions
  .speed/shared/defects/         defect state
  .speed/shared/events/          event log
  .speed/shared/roster/          team roster
  .speed/shared/proposals/       knowledge proposals
  .speed/shared/active_feature   active feature marker
  .speed/local/dashboard.db      SQLite cache
  .speed/context/                CSG (unchanged)

Detection: multiplayer mode is active when .speed/shared/ directory exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class SpeedPaths:
    """Resolves .speed/ paths for either single-player or multiplayer layout."""

    def __init__(self, project_root: Path) -> None:
        self.root = Path(project_root)
        self.mp_enabled = (self.root / ".speed" / "shared").is_dir()

    # ── Feature paths (split in MP mode) ─────────────────────────

    @property
    def features_dir(self) -> Path:
        """Where declarative feature state lives (tasks, contracts, spec_path)."""
        if self.mp_enabled:
            return self.root / ".speed" / "shared" / "features"
        return self.root / ".speed" / "features"

    @property
    def local_features_dir(self) -> Path:
        """Where runtime feature state lives (logs, state.json, PIDs)."""
        if self.mp_enabled:
            return self.root / ".speed" / "local" / "features"
        return self.root / ".speed" / "features"

    def feature_shared(self, name: str) -> Path:
        """Tasks, contracts, spec_path for a feature."""
        return self.features_dir / name

    def feature_local(self, name: str) -> Path:
        """Logs, state.json, running/, support/ for a feature."""
        return self.local_features_dir / name

    def feature_names(self) -> list[str]:
        """List all feature names from the declarative side."""
        if not self.features_dir.is_dir():
            return []
        return sorted(
            d.name for d in self.features_dir.iterdir() if d.is_dir()
        )

    # ── Ceremony ─────────────────────────────────────────────────

    def ceremony_dir(self, name: str) -> Path:
        return self.feature_shared(name)

    def ceremony_state(self, name: str) -> Path:
        return self.feature_shared(name) / "ceremony.json"

    def ceremony_intent(self, name: str) -> Path:
        return self.feature_shared(name) / "intent.json"

    def ceremony_context_package(self, name: str) -> Path:
        return self.feature_shared(name) / "context-package.json"

    def ceremony_suggestions(self, name: str) -> Path:
        return self.feature_shared(name) / "suggestions.json"

    def ceremony_commit_record(self, name: str, spec_type: str = "") -> Path:
        if spec_type:
            return self.feature_shared(name) / f"commit-{spec_type}.json"
        return self.feature_shared(name) / "commit.json"

    def ceremony_validation_snapshot(self, name: str) -> Path:
        return self.feature_shared(name) / "validation-at-commit.json"

    def ceremony_draft(self, name: str, spec_type: str = "") -> Path:
        if spec_type:
            return self.feature_shared(name) / f"draft-{spec_type}.json"
        return self.feature_shared(name) / "draft.json"

    def ceremony_validation_state(self, name: str, spec_type: str = "prd") -> Path:
        return self.feature_shared(name) / f"validation-state-{spec_type}.json"

    def ceremony_claim(self, name: str, spec_type: str) -> Path:
        return self.feature_shared(name) / f"claim-{spec_type}.json"

    def ceremony_decomposition(self, name: str, spec_type: str = "") -> Path:
        if spec_type:
            return self.feature_shared(name) / f"decomposition-{spec_type}.json"
        return self.feature_shared(name) / "decomposition.json"

    def ceremony_ratification(self, name: str, spec_type: str) -> Path:
        return self.feature_shared(name) / f"ratification-{spec_type}.json"

    # ── Memory / Knowledge ───────────────────────────────────────

    @property
    def memory_dir(self) -> Path:
        if self.mp_enabled:
            return self.root / ".speed" / "shared" / "knowledge"
        return self.root / ".speed" / "memory"

    @property
    def observations_dir(self) -> Path:
        return self.memory_dir / "observations"

    @property
    def conventions_path(self) -> Path:
        return self.memory_dir / "conventions.json"

    # ── Defects ──────────────────────────────────────────────────

    @property
    def defects_dir(self) -> Path:
        if self.mp_enabled:
            return self.root / ".speed" / "shared" / "defects"
        return self.root / ".speed" / "defects"

    # ── Context (unchanged across modes) ─────────────────────────

    @property
    def context_dir(self) -> Path:
        return self.root / ".speed" / "context"

    @property
    def repository_digest_path(self) -> Path:
        return self.context_dir / "repository-digest.json"

    @property
    def repository_digest_status_path(self) -> Path:
        return self.context_dir / "repository-digest-status.json"

    # ── Singletons ───────────────────────────────────────────────

    @property
    def active_feature_path(self) -> Path:
        if self.mp_enabled:
            return self.root / ".speed" / "shared" / "active_feature"
        return self.root / ".speed" / "active_feature"

    @property
    def db_path(self) -> Path:
        if self.mp_enabled:
            return self.root / ".speed" / "local" / "dashboard.db"
        return self.root / ".speed" / "dashboard.db"

    # ── MP-only paths (None in single-player) ────────────────────

    @property
    def events_dir(self) -> Optional[Path]:
        if not self.mp_enabled:
            return None
        return self.root / ".speed" / "shared" / "events"

    @property
    def roster_dir(self) -> Optional[Path]:
        if not self.mp_enabled:
            return None
        return self.root / ".speed" / "shared" / "roster"

    @property
    def proposals_dir(self) -> Optional[Path]:
        if not self.mp_enabled:
            return None
        return self.root / ".speed" / "shared" / "proposals"


# ── Module-level cache ───────────────────────────────────────────

_cache: dict[str, SpeedPaths] = {}


def get_paths(project_root: Path | str) -> SpeedPaths:
    """Get or create a cached SpeedPaths instance for a project root."""
    key = str(project_root)
    if key not in _cache:
        _cache[key] = SpeedPaths(Path(project_root))
    return _cache[key]
