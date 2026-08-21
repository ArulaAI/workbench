"""Human correction extraction for SPEED's learning infrastructure.

Extraction-time signals (steps 11-14):
  Step 11: Retry guidance (from task JSON review_feedback)
  Step 12: Skip flags (from skipped-gates.json)
  Step 13: Forced approvals (task verdict vs review log)
  Step 14: Defect rejections (from defect state.json)

Post-merge path (speed learn --post-merge):
  Diffs SPEED's task branch tips against merged HEAD,
  classifies changes deterministically, creates observations.

All steps are deterministic. No LLM calls.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .extract import Observation, observation_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _obs(feature: str, task_id: str, obs_type: str,
         detail: dict, weight: float) -> Observation:
    """Build an Observation with computed ID and timestamp."""
    return Observation(
        id=observation_id(feature, task_id, "human", obs_type, detail),
        feature=feature,
        stage="human",
        task_id=task_id,
        timestamp=_now_iso(),
        observation_type=obs_type,
        detail=detail,
        weight=weight,
    )


def _agent_for_task(task: dict) -> str:
    """Determine which agent a task failure should attribute to."""
    return "developer"


# ── Step 11: Retry guidance ─────────────────────────────────────────


def step11_retry_guidance(
    tasks: list[dict], feature: str,
) -> list[Observation]:
    """Extract human guidance from retry attempts.

    Parses review_feedback for "--- Attempt N ---" / "Human guidance:"
    markers written by retry.sh.
    """
    observations: list[Observation] = []
    for task in tasks:
        feedback = task.get("review_feedback", "")
        if not feedback or not isinstance(feedback, str):
            continue
        for match in re.finditer(
            r"--- Attempt (\d+) ---\nFailed with: (.*?)\n"
            r"Human guidance: (.*?)(?=\n--- Attempt|\Z)",
            feedback, re.DOTALL,
        ):
            attempt = int(match.group(1))
            error = match.group(2).strip()
            guidance = match.group(3).strip()
            if not guidance:
                continue
            detail = {
                "change_type": "guidance",
                "guidance_text": guidance,
                "task_id": task.get("id", ""),
                "attempt": attempt,
                "original_error": error,
                "task_succeeded": task.get("status") == "done",
                "agent_attribution": [_agent_for_task(task)],
            }
            observations.append(_obs(
                feature, task.get("id", "*"),
                "human_override", detail, weight=2.5,
            ))
    return observations


# ── Step 12: Skip flags ─────────────────────────────────────────────


def step12_skip_flags(
    feature_dir: Path, feature: str,
) -> list[Observation]:
    """Extract gate skip events from skipped-gates.json."""
    skip_file = feature_dir / "logs" / "skipped-gates.json"
    if not skip_file.exists():
        return []
    observations: list[Observation] = []
    for line in skip_file.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        detail = {
            "change_type": "skip",
            "gate_name": entry.get("gate", ""),
            "pipeline_stage": entry.get("stage", ""),
        }
        observations.append(_obs(
            feature, "*",
            "human_override", detail, weight=0.5,
        ))
    return observations


# ── Step 13: Forced approvals ───────────────────────────────────────


def step13_forced_approvals(
    tasks: list[dict], feature: str, logs_dir: Path,
) -> list[Observation]:
    """Detect tasks approved without proper review."""
    observations: list[Observation] = []
    for task in tasks:
        if task.get("review_verdict") != "approve":
            continue
        tid = task.get("id", "")
        log_path = logs_dir / f"review-{tid}.json"

        forced = False
        reviewer_findings: list = []

        if not log_path.exists():
            forced = True
        else:
            try:
                review_data = json.loads(log_path.read_text())
                if review_data.get("verdict") == "request_changes":
                    forced = True
                    reviewer_findings = review_data.get("issues", [])
            except (json.JSONDecodeError, OSError):
                pass

        if not forced:
            continue

        detail = {
            "change_type": "forced_approval",
            "task_id": tid,
            "reviewer_verdict": (
                "request_changes" if reviewer_findings else "no_review"
            ),
            "reviewer_findings": reviewer_findings[:5],
            "agent_attribution": ["reviewer"],
        }
        observations.append(_obs(
            feature, tid,
            "human_override", detail, weight=2.0,
        ))
    return observations


# ── Step 14: Defect rejections ──────────────────────────────────────


def step14_defect_rejections(
    defects_dir: Path, feature: str,
) -> list[Observation]:
    """Extract rejected defects as human override signals."""
    if not defects_dir.is_dir():
        return []
    observations: list[Observation] = []
    for state_file in sorted(defects_dir.glob("*/state.json")):
        try:
            state = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if state.get("status") != "rejected":
            continue
        defect_name = state_file.parent.name
        triage: dict = {}
        triage_path = state_file.parent / "triage.json"
        if triage_path.exists():
            try:
                triage = json.loads(triage_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        detail = {
            "change_type": "defect_rejection",
            "defect_name": defect_name,
            "defect_type": triage.get(
                "defect_type", state.get("defect_type")
            ),
            "complexity": triage.get(
                "complexity", state.get("complexity")
            ),
            "triage_summary": triage.get("summary", ""),
            "agent_attribution": ["debugger"],
        }
        observations.append(_obs(
            feature, "*",
            "human_override", detail, weight=1.5,
        ))
    return observations


# ── Post-merge path ─────────────────────────────────────────────────


_NOISE_FILES = frozenset({
    "CHANGELOG.md", "CHANGELOG", "changelog.md",
    "VERSION", "version.txt", ".version",
    "package-lock.json", "yarn.lock", "Gemfile.lock",
    "poetry.lock", "Pipfile.lock", "composer.lock",
    "pnpm-lock.yaml", "Cargo.lock",
})


@dataclass
class DiffHunk:
    """A single hunk from a unified diff."""

    file: str
    header: str
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)

    @property
    def change_type(self) -> str:
        """Deterministic change type from diff structure."""
        has_removed = any(l.strip() for l in self.removed)
        has_added = any(l.strip() for l in self.added)

        if has_removed and has_added:
            removed_stripped = [l.strip() for l in self.removed if l.strip()]
            added_stripped = [l.strip() for l in self.added if l.strip()]
            if removed_stripped == added_stripped:
                return "cosmetic"
            return "transformative"
        elif has_added and not has_removed:
            return "additive"
        elif has_removed and not has_added:
            return "subtractive"
        return "unknown"

    @property
    def hunk_summary(self) -> str:
        added = len([l for l in self.added if l.strip()])
        removed = len([l for l in self.removed if l.strip()])
        return f"+{added}/-{removed} lines"


def _git(project_root: Path, *args: str) -> str | None:
    """Run a git command, return stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root)] + list(args),
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _task_files(task: dict) -> list[str]:
    """Extract file list from task JSON."""
    files: list[str] = []
    for key in ("files_to_modify", "files_to_create"):
        val = task.get(key, [])
        if isinstance(val, list):
            files.extend(str(f) for f in val if f)
    if not files:
        touched = task.get("files_touched", [])
        if isinstance(touched, str):
            files = [f.strip() for f in touched.split(",") if f.strip()]
        elif isinstance(touched, list):
            files = [str(f) for f in touched if f]
    return files


def _is_noise_file(file_path: str) -> bool:
    """Check if a file is a noise artifact (changelog, lock file, etc.)."""
    return Path(file_path).name in _NOISE_FILES


def parse_diff_hunks(diff_text: str) -> list[DiffHunk]:
    """Parse unified diff into individual hunks."""
    hunks: list[DiffHunk] = []
    current_file: str | None = None
    current_hunk: DiffHunk | None = None

    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[2].removeprefix("a/")
        elif line.startswith("@@"):
            if current_hunk and (current_hunk.removed or current_hunk.added):
                hunks.append(current_hunk)
            current_hunk = DiffHunk(
                file=current_file or "unknown",
                header=line,
            )
        elif current_hunk is not None:
            if line.startswith("-") and not line.startswith("---"):
                current_hunk.removed.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                current_hunk.added.append(line[1:])
            elif line.startswith(" "):
                current_hunk.context.append(line[1:])

    if current_hunk and (current_hunk.removed or current_hunk.added):
        hunks.append(current_hunk)

    return hunks


def _attribute_agent(file_path: str, change_type: str) -> list[str]:
    """Rule-based agent attribution from file path."""
    agents: list[str] = []
    if file_path.startswith("agents/"):
        agents.append("architect")
    else:
        agents.append("developer")
    if change_type == "subtractive":
        agents.append("guardian")
    return agents


def _fetch_pr_comments(
    feature_dir: Path, project_root: Path,
) -> dict[str, list[str]]:
    """Fetch PR comments grouped by file path. Optional enrichment.

    Returns empty dict if gh is unavailable, repo is non-GitHub,
    or PR number is unknown.
    """
    comments_by_file: dict[str, list[str]] = {}

    pr_file = feature_dir / "pr-number"
    if not pr_file.exists():
        return comments_by_file

    try:
        pr_number = pr_file.read_text().strip()
        if not pr_number.isdigit():
            return comments_by_file
    except OSError:
        return comments_by_file

    remote = _git(project_root, "remote", "get-url", "origin")
    if not remote:
        return comments_by_file

    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote)
    if not match:
        return comments_by_file

    owner, repo = match.group(1), match.group(2)

    try:
        result = subprocess.run(
            ["gh", "api",
             f"repos/{owner}/{repo}/pulls/{pr_number}/comments"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return comments_by_file

        for comment in json.loads(result.stdout):
            path = comment.get("path", "")
            body = comment.get("body", "")
            if path and body:
                comments_by_file.setdefault(path, []).append(body)
    except (subprocess.TimeoutExpired, FileNotFoundError,
            json.JSONDecodeError):
        pass

    return comments_by_file


def find_speed_branches(
    feature_dir: Path, project_root: Path,
) -> dict[str, dict]:
    """Map task branches to their tip SHAs and metadata.

    Returns {task_id: {"branch": str, "tip": str, "files": list,
    "task": dict}}. Tasks with missing or deleted branches are skipped.
    """
    branches: dict[str, dict] = {}
    tasks_dir = feature_dir / "tasks"
    if not tasks_dir.is_dir():
        return branches

    for task_file in sorted(tasks_dir.glob("*.json")):
        try:
            task = json.loads(task_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        branch = task.get("branch", "")
        if not branch:
            continue

        tip = _git(project_root, "rev-parse", "--verify", branch)
        if not tip:
            continue

        task_id = str(task.get("id", task_file.stem))
        branches[task_id] = {
            "branch": branch,
            "tip": tip,
            "files": _task_files(task),
            "task": task,
        }

    return branches


def extract_post_merge(
    feature: str,
    feature_dir: Path,
    project_root: Path,
) -> tuple[list[Observation], list[str]]:
    """Post-merge correction extraction.

    Diffs SPEED's task branch tips against merged HEAD, classifies
    changes deterministically, creates observations.

    Returns (observations, warnings).
    """
    observations: list[Observation] = []
    warnings: list[str] = []

    # Step 1: Find task branches
    branch_map = find_speed_branches(feature_dir, project_root)
    if not branch_map:
        warnings.append(
            "No task branches found — cannot extract post-merge corrections"
        )
        return observations, warnings

    # Fetch PR comments (optional enrichment)
    pr_comments = _fetch_pr_comments(feature_dir, project_root)

    # Get HEAD commit info once
    head_sha = _git(project_root, "rev-parse", "HEAD") or ""
    head_msg = _git(
        project_root, "log", "-1", "--format=%s", "HEAD",
    ) or ""

    # Steps 2-6: Per-task diff and classification
    tasks_with_changes = 0
    all_task_ids: list[str] = []
    all_files: set[str] = set()

    for task_id, info in sorted(branch_map.items()):
        tip = info["tip"]
        task_files = info["files"]
        all_task_ids.append(task_id)
        all_files.update(task_files)

        if not task_files:
            warnings.append(f"Task {task_id}: no file list, skipping")
            continue

        # Git diff: task branch tip vs HEAD, scoped to task files
        diff_args = ["diff", tip, "HEAD", "--unified=3", "--"]
        diff_args.extend(task_files)
        diff_text = _git(project_root, *diff_args) or ""

        if not diff_text:
            continue

        hunks = parse_diff_hunks(diff_text)
        if not hunks:
            continue

        tasks_with_changes += 1

        for hunk in hunks:
            if _is_noise_file(hunk.file):
                continue

            ct = hunk.change_type
            if ct == "unknown":
                continue

            weight = 0.1 if ct == "cosmetic" else 2.5
            agents = _attribute_agent(hunk.file, ct)
            file_comments = pr_comments.get(hunk.file, [])

            detail = {
                "change_type": ct,
                "file": hunk.file,
                "commit_sha": head_sha[:12],
                "commit_message": head_msg[:200],
                "hunk_summary": hunk.hunk_summary,
                "human_comment": file_comments[0] if file_comments else None,
                "agent_attribution": agents,
                "task_id": task_id,
            }
            observations.append(_obs(
                feature, task_id,
                "human_override", detail, weight=weight,
            ))

    # Zero-delta detection
    if tasks_with_changes == 0 and branch_map:
        detail = {
            "tasks_approved": len(all_task_ids),
            "files_approved": len(all_files),
            "task_ids": all_task_ids,
        }
        observations.append(_obs(
            feature, "*",
            "human_approved", detail, weight=0.5,
        ))

    return observations, warnings
