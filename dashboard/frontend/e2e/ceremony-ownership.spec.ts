/**
 * End-to-end Playwright tests for the per-spec ownership feature.
 *
 * Preconditions (same as the existing task-board-layout.spec.ts):
 * - Dashboard is running at http://localhost:3000 (frontend) and
 *   http://localhost:4440 (GraphQL API)
 * - SPEED_ACTOR / SPEED_ACTOR_EMAIL env vars are set on the dashboard
 *   process; these tests assume "Sanjay <sanjay@example.com>" because
 *   that's the default test identity.
 * - The repo has `.speed/shared/` active (multiplayer mode)
 *
 * Because ownership actions are file-backed, each test seeds its own
 * ceremony directory via direct filesystem writes and cleans up after.
 * This sidesteps the LLM-dependent `generateDraft` path entirely —
 * drafts are written directly rather than generated — so the tests
 * respect the hard "no LLM calls" rule.
 */

import { test, expect } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

const BASE = "http://localhost:3000";
const PROJECT_ROOT = path.resolve(__dirname, "../../../");
const SHARED_FEATURES = path.join(PROJECT_ROOT, ".speed/shared/features");
const ROSTER_DIR = path.join(PROJECT_ROOT, ".speed/shared/roster");

const NOW_ISO = () => new Date().toISOString();
const FIFTEEN_MIN_AGO = () => new Date(Date.now() - 15 * 60 * 1000).toISOString();

type CeremonyFixture = {
  feature: string;
  authorName: string;
  authorEmail: string;
  drafted: string[];
  claimedBy?: Record<string, { name: string; email: string; stale?: boolean }>;
  committedBy?: Record<string, { name: string; email: string }>;
};

function seedCeremony(fx: CeremonyFixture): string {
  const dir = path.join(SHARED_FEATURES, fx.feature);
  fs.mkdirSync(dir, { recursive: true });

  // ceremony.json
  const revId = "rev0001";
  const now = NOW_ISO();
  const state = {
    feature_name: fx.feature,
    author: fx.authorName,
    author_email: fx.authorEmail,
    created_at: now,
    is_multiplayer: true,
    current_revision: revId,
    revision_count: 1,
    revisions: {
      [revId]: {
        revision_id: revId,
        parent_id: null,
        status: "drafting",
        spec_content_hash: "a".repeat(64),
        context_package_hash: "b".repeat(64),
        validation_hash: "c".repeat(64),
        created_at: now,
        reason: "initial",
      },
    },
    reflog: [],
  };
  fs.writeFileSync(path.join(dir, "ceremony.json"), JSON.stringify(state, null, 2));

  // intent.json
  fs.writeFileSync(
    path.join(dir, "intent.json"),
    JSON.stringify(
      {
        text: `E2E test: ${fx.feature}`,
        author: fx.authorName,
        author_email: fx.authorEmail,
        created_at: now,
        feature_name: fx.feature,
      },
      null,
      2
    )
  );

  // Drafts
  for (const specType of fx.drafted) {
    fs.writeFileSync(
      path.join(dir, `draft-${specType}.json`),
      JSON.stringify(
        {
          feature_name: fx.feature,
          spec_type: specType,
          content: `# ${fx.feature} ${specType}\n\n## Problem\n\nE2E seed content for ${specType}.\n\n## Scope\n\nTest fixture.\n`,
          file_path: `specs/product/${fx.feature}.md`,
          template_name: specType,
          generated_at: now,
          child_specs: [],
        },
        null,
        2
      )
    );
  }

  // Claims
  if (fx.claimedBy) {
    for (const [specType, claim] of Object.entries(fx.claimedBy)) {
      const activityAt = claim.stale ? FIFTEEN_MIN_AGO() : now;
      fs.writeFileSync(
        path.join(dir, `claim-${specType}.json`),
        JSON.stringify(
          {
            spec_type: specType,
            claimant: claim.name,
            claimant_email: claim.email,
            claimed_at: activityAt,
            last_activity_at: activityAt,
            released_at: null,
          },
          null,
          2
        )
      );
    }
  }

  // Commit records
  if (fx.committedBy) {
    for (const [specType, commit] of Object.entries(fx.committedBy)) {
      fs.writeFileSync(
        path.join(dir, `commit-${specType}.json`),
        JSON.stringify(
          {
            feature_name: fx.feature,
            spec_type: specType,
            revision_id: revId,
            claimant: commit.name,
            claimant_email: commit.email,
            committed_at: now,
            validation_state_ref: "abc123",
            context_package_ref: "",
            suggestion_history: {
              received: 0,
              accepted: 0,
              dismissed: { count: 0, reasons: [] },
            },
            spec_path: `specs/product/${fx.feature}.md`,
            decomposition_ref: null,
            is_multiplayer: true,
            ratification_threshold: 1,
            ratification_status: "pending",
          },
          null,
          2
        )
      );
      // Retire the claim on commit (set released_at)
      const claimPath = path.join(dir, `claim-${specType}.json`);
      if (fs.existsSync(claimPath)) {
        const existing = JSON.parse(fs.readFileSync(claimPath, "utf8"));
        existing.released_at = now;
        existing.last_activity_at = now;
        fs.writeFileSync(claimPath, JSON.stringify(existing, null, 2));
      } else {
        fs.writeFileSync(
          claimPath,
          JSON.stringify(
            {
              spec_type: specType,
              claimant: commit.name,
              claimant_email: commit.email,
              claimed_at: now,
              last_activity_at: now,
              released_at: now,
            },
            null,
            2
          )
        );
      }
    }
  }

  return dir;
}

function cleanupCeremony(feature: string): void {
  const dir = path.join(SHARED_FEATURES, feature);
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function ensureRosterMember(name: string, email: string): void {
  if (!fs.existsSync(ROSTER_DIR)) return;
  const file = path.join(ROSTER_DIR, `${name.toLowerCase()}.json`);
  if (!fs.existsSync(file)) {
    fs.writeFileSync(file, JSON.stringify({ name, email }) + "\n");
  }
}

// ── Scenarios ────────────────────────────────────────────────────


test.describe("Per-Spec Ownership — Tab Bar & Claim Chrome", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("drafted PRD shows claimant badge for current actor", async ({ page }) => {
    const feature = "e2e-ownership-tab-mine";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd"],
      claimedBy: {
        prd: { name: "Sanjay", email: "sanjay@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // Tab bar should render the PRD tab with Sanjay's name inline
      // (the mine variant of TabClaimBadge).
      await expect(page.getByLabel("Owned by you")).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });

  test("unclaimed Design tab shows Claim button", async ({ page }) => {
    const feature = "e2e-ownership-tab-unclaimed";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd", "design"],
      claimedBy: {
        prd: { name: "Sanjay", email: "sanjay@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // At least one "Claim spec" button should be visible (the one on
      // the Design tab since PRD is claimed by Sanjay).
      const claimButtons = page.getByRole("button", { name: "Claim spec" });
      await expect(claimButtons.first()).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });

  test("Design claimed by other renders read-only view for Sanjay", async ({ page }) => {
    const feature = "e2e-ownership-tab-other";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd", "design"],
      claimedBy: {
        prd: { name: "Sanjay", email: "sanjay@example.com" },
        design: { name: "Priya", email: "priya@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // Click the Design tab
      await page.getByRole("button", { name: /^Design/ }).first().click();
      await page.waitForTimeout(300);

      // Read-only banner should appear
      const banner = page.getByRole("status").filter({ hasText: /read-only/i });
      await expect(banner).toBeVisible();
      await expect(banner).toContainText("Priya");
    } finally {
      cleanupCeremony(feature);
    }
  });
});


test.describe("Per-Spec Ownership — Progress Overview", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("ceremony with three drafted specs shows three rows", async ({ page }) => {
    const feature = "e2e-ownership-progress-three";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd", "design", "rfc"],
      claimedBy: {
        prd: { name: "Sanjay", email: "sanjay@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // Expand the Progress section if it's collapsed (3 rows triggers
      // the default-open threshold > 3; here we have 3 exactly so it's
      // likely collapsed — click the header to expand).
      const region = page.getByRole("region", { name: /ceremony progress/i });
      // If not visible, look for the collapsed header button
      const isExpanded = await region.isVisible().catch(() => false);
      if (!isExpanded) {
        const header = page.getByRole("button", { name: /^Progress/i }).first();
        if (await header.isVisible()) await header.click();
      }

      // PRD / Design / RFC labels should all be in the overview
      await expect(page.getByText("PRD", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Design", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("RFC", { exact: true }).first()).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });

  test("committed spec shows committed status pill", async ({ page }) => {
    const feature = "e2e-ownership-progress-committed";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd"],
      committedBy: {
        prd: { name: "Sanjay", email: "sanjay@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // Expand the overview (1 row, collapsed by default since <= 3)
      const header = page.getByRole("button", { name: /^Progress/i }).first();
      if (await header.isVisible()) await header.click();

      // The progress summary should reflect 1 committed spec
      const region = page.getByRole("region", { name: /ceremony progress/i });
      await expect(region).toContainText(/1\s*of\s*1\s*committed/);
    } finally {
      cleanupCeremony(feature);
    }
  });
});


test.describe("Per-Spec Ownership — CommitBar scope", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("commit bar shows SCOPE PRD label on PRD tab", async ({ page }) => {
    const feature = "e2e-ownership-commitbar-scope";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd"],
      claimedBy: {
        prd: { name: "Sanjay", email: "sanjay@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // SCOPE label should render at the left of the commit bar
      await expect(page.getByText(/SCOPE/)).toBeVisible();
      await expect(page.getByText("PRD").first()).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });

  test("non-claimant sees disabled Commit button with 'Claimed by' caption", async ({ page }) => {
    const feature = "e2e-ownership-commitbar-disabled";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd"],
      claimedBy: {
        prd: { name: "Priya", email: "priya@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // Disabled caption should reference Priya
      await expect(page.getByText(/Claimed by Priya/i)).toBeVisible();

      // Commit button should be disabled
      const commitBtn = page.getByRole("button", { name: /Commit PRD, disabled/i });
      await expect(commitBtn).toBeDisabled();
    } finally {
      cleanupCeremony(feature);
    }
  });
});


test.describe("Per-Spec Ownership — Read-only diagonal stripe", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("non-claimant editor renders with readonly data attribute", async ({ page }) => {
    const feature = "e2e-ownership-stripe";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd"],
      claimedBy: {
        prd: { name: "Priya", email: "priya@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // The SpecEditor container has data-readonly="true" when readOnly
      const editor = page.locator('[data-readonly="true"]').first();
      await expect(editor).toBeAttached();
    } finally {
      cleanupCeremony(feature);
    }
  });
});


test.describe("Per-Spec Ownership — Stale claim takeover (O9)", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("stale claim shows amber badge and Takeover action", async ({ page }) => {
    const feature = "e2e-ownership-stale-takeover";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd"],
      claimedBy: {
        prd: { name: "Priya", email: "priya@example.com", stale: true },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // The stale badge should render with Priya's name and a
      // Takeover button (only shown for stale claims by other actors).
      // The ReadOnlyBanner for stale claims shows "Stale" and
      // the claimant name with a Takeover action.
      await expect(page.getByText(/stale/i).first()).toBeVisible();
      const takeoverBtn = page.getByRole("button", { name: /take over/i });
      await expect(takeoverBtn).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });
});


test.describe("Per-Spec Ownership — Contributor banner (non-author)", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("contributor sees read-only banner with author name on unclaimed spec", async ({ page }) => {
    // Ceremony authored by Priya, Sanjay is viewing (contributor).
    // The PRD is drafted but unclaimed — Sanjay should see the
    // ContributorBanner with "authored by Priya".
    const feature = "e2e-ownership-contributor-banner";
    seedCeremony({
      feature,
      authorName: "Priya",
      authorEmail: "priya@example.com",
      drafted: ["prd"],
      // No claim — unclaimed tab
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // ContributorBanner should show "Read-only" and "authored by Priya"
      await expect(page.getByText(/Read-only/i).first()).toBeVisible();
      await expect(page.getByText("Priya").first()).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });
});


test.describe("Per-Spec Ownership — Suggestion sidebar for non-claimants (O4-O5)", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("suggestion sidebar toggle shows unresolved count badge", async ({ page }) => {
    const feature = "e2e-ownership-suggestion-badge";
    const dir = seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd"],
      claimedBy: {
        prd: { name: "Sanjay", email: "sanjay@example.com" },
      },
    });

    // Seed a suggestion
    const suggestionsPath = path.join(dir, "suggestions.json");
    const suggestions = [
      {
        id: "sug-test-001",
        author: "Priya",
        author_email: "priya@example.com",
        revision_id: "rev0001",
        spec_type: "prd",
        section_id: "problem",
        section_title: "Problem",
        section_content_hash: "x".repeat(64),
        text: "Consider adding more context about the failure modes.",
        status: "unresolved",
        outdated: false,
        created_at: NOW_ISO(),
        updated_at: null,
        resolution: null,
        thread: [],
      },
    ];
    fs.writeFileSync(suggestionsPath, JSON.stringify(suggestions, null, 2));

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // The suggestion toggle button should have a badge with "1"
      const toggleBtn = page.getByRole("button", { name: /suggestions/i });
      await expect(toggleBtn).toBeVisible();

      // The badge count shows the unresolved count
      await expect(page.locator("text=1").first()).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });
});


test.describe("Per-Spec Ownership — Ratification view (MP)", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("review page shows committed spec with approve/reject controls", async ({ page }) => {
    const feature = "e2e-ownership-ratify-view";
    const dir = seedCeremony({
      feature,
      authorName: "Priya",
      authorEmail: "priya@example.com",
      drafted: ["prd"],
      claimedBy: {
        prd: { name: "Priya", email: "priya@example.com" },
      },
      committedBy: {
        prd: { name: "Priya", email: "priya@example.com" },
      },
    });

    // Update ceremony state to COMMITTED
    const ceremonyPath = path.join(dir, "ceremony.json");
    const ceremony = JSON.parse(fs.readFileSync(ceremonyPath, "utf8"));
    ceremony.revisions.rev0001.status = "committed";
    fs.writeFileSync(ceremonyPath, JSON.stringify(ceremony, null, 2));

    // Add ratification state (pending)
    fs.writeFileSync(
      path.join(dir, "ratification-prd.json"),
      JSON.stringify(
        {
          spec_type: "prd",
          revision_id: "rev0001",
          ratified: false,
          verdicts: [],
          source: "roster",
        },
        null,
        2
      )
    );

    try {
      await page.goto(`${BASE}/define/${feature}/review`);
      await page.waitForLoadState("networkidle");

      // The review page should show "Read-only" header
      await expect(page.getByText(/Read-only/i).first()).toBeVisible();

      // Approve button should be visible for Sanjay (non-author)
      const approveBtn = page.getByRole("button", { name: /approve/i });
      await expect(approveBtn).toBeVisible();

      // Reject button should be visible
      const rejectBtn = page.getByRole("button", { name: /reject/i });
      await expect(rejectBtn).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });

  test("SP mode redirects /review to /define/:feature", async ({ page }) => {
    const feature = "e2e-ownership-ratify-sp-redirect";
    const dir = seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd"],
    });

    // Override to single-player
    const ceremonyPath = path.join(dir, "ceremony.json");
    const ceremony = JSON.parse(fs.readFileSync(ceremonyPath, "utf8"));
    ceremony.is_multiplayer = false;
    fs.writeFileSync(ceremonyPath, JSON.stringify(ceremony, null, 2));

    try {
      await page.goto(`${BASE}/define/${feature}/review`);
      // Should redirect to the main define page
      await page.waitForURL(`**/define/${feature}`, { timeout: 5000 });
      expect(page.url()).toContain(`/define/${feature}`);
      expect(page.url()).not.toContain("/review");
    } finally {
      cleanupCeremony(feature);
    }
  });
});


test.describe("Per-Spec Ownership — Claim History Panel", () => {
  test.beforeAll(() => {
    ensureRosterMember("Sanjay", "sanjay@example.com");
    ensureRosterMember("Priya", "priya@example.com");
  });

  test("claim history panel renders timeline entries", async ({ page }) => {
    const feature = "e2e-ownership-claim-history";
    seedCeremony({
      feature,
      authorName: "Sanjay",
      authorEmail: "sanjay@example.com",
      drafted: ["prd", "design"],
      claimedBy: {
        prd: { name: "Sanjay", email: "sanjay@example.com" },
        design: { name: "Priya", email: "priya@example.com" },
      },
    });

    try {
      await page.goto(`${BASE}/define/${feature}`);
      await page.waitForLoadState("networkidle");

      // Expand the Claim Activity panel (collapsed by default)
      const historyToggle = page.getByRole("button", { name: /Claim Activity/i });
      await expect(historyToggle).toBeVisible();
      await historyToggle.click();

      // Should show entries for both Sanjay and Priya
      await expect(page.getByText("Sanjay").first()).toBeVisible();
      await expect(page.getByText("Priya").first()).toBeVisible();
    } finally {
      cleanupCeremony(feature);
    }
  });
});
