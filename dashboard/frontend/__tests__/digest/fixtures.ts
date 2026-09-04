import type {
  RepositoryDigestData,
  RepositoryDigestBuildStatus,
} from "@/lib/graphql/queries/repository-digest";

// Shared across the /digest/* screen test files — vi.mock() hoisting means
// each test file still owns its own mock wiring, but the fixture data
// itself is identical everywhere and worth keeping in one place.

export const baseDigest: RepositoryDigestData = {
  schemaVersion: 1,
  status: "COMPLETE",
  effectiveState: "CURRENT",
  generatedAt: "2026-03-15T10:00:00Z",
  freshness: {
    state: "CURRENT",
    indexedGitHead: "abc1234567",
    currentGitHead: "abc1234567",
    generatedAt: "2026-03-15T10:00:00Z",
    staleReasons: [],
  },
  identity: { name: "speed", summary: "An orchestration framework.", confidence: "DERIVED", evidence: [] },
  footprint: {
    fileCount: 120,
    lineCount: 34000,
    symbolCount: 500,
    domainCount: 3,
    languages: [
      { name: "python", files: 80, lines: 20000, percent: 60 },
      { name: "typescript", files: 40, lines: 14000, percent: 40 },
    ],
  },
  domains: [
    {
      id: "cluster-core",
      label: "Core",
      summary: "Core orchestration logic.",
      confidence: "DERIVED",
      fileCount: 40,
      symbolCount: 200,
      representativeFiles: ["lib/context/repository_digest.py"],
      representativeSymbols: [],
      dependsOn: [],
      usedBy: ["cluster-ui"],
      evidence: [{ source: "semantic_graph", path: "lib/context/repository_digest.py", line: null, symbol: null, artifactKey: null, description: "evidence" }],
      lane: "services",
    },
    {
      id: "cluster-ui",
      label: "Dashboard UI",
      summary: "Frontend dashboard.",
      confidence: "DERIVED",
      fileCount: 25,
      symbolCount: 90,
      representativeFiles: ["dashboard/frontend/app/digest/page.tsx"],
      representativeSymbols: [],
      dependsOn: ["cluster-core"],
      usedBy: [],
      evidence: [],
      lane: "frontend",
    },
  ],
  relationships: [
    {
      source: "cluster-ui",
      target: "cluster-core",
      weight: 12,
      evidenceType: "verified",
      sampleReferences: [{ sourceSymbol: "dashboard/frontend/app/digest/page.tsx::DigestPage", targetSymbol: "lib/context/repository_digest.py::build_repository_digest" }],
    },
  ],
  commands: [
    { purpose: "TEST", command: "pytest tests/", workingDirectory: ".", confidence: "CONFIRMED", evidence: [] },
    { purpose: "TEST", command: "npm run test", workingDirectory: "dashboard/frontend", confidence: "CONFIRMED", evidence: [] },
    { purpose: "BUILD", command: "npm run build", workingDirectory: "dashboard/frontend", confidence: "CONFIRMED", evidence: [] },
  ],
  hotspots: [
    {
      symbolId: "lib/context/repository_digest.py::build_repository_digest",
      name: "build_repository_digest",
      file: "lib/context/repository_digest.py",
      line: 120,
      domainId: "cluster-core",
      reason: "High blast radius",
      blastRadius: 40,
      dependents: 11,
    },
  ],
  conventions: [
    { text: "Use snake_case for Python modules.", scope: ["lib"], confidence: "DERIVED", evidence: [] },
  ],
  risks: [],
  gaps: [],
  readiness: [
    { capability: "semantic_graph", status: "AVAILABLE", reason: null, remediation: null },
  ],
  warnings: ["2 domains have no distinguishing label and were marked unresolved."],
  coverageStats: {
    sourceFilesTotal: 150,
    sourceFilesParsed: 139,
    parseCoveragePct: 92.7,
    symbolsExtracted: 500,
    referencesExtracted: 1200,
  },
  entrypoints: [
    { name: "app.py", file: "lib/app.py", kind: "run" },
  ],
  annotatedTree: [
    { path: "lib", fileCount: 80, totalLines: 20000, dominantDomainLabel: "Core" },
    { path: "dashboard", fileCount: 40, totalLines: 14000, dominantDomainLabel: null },
  ],
  readingPath: [
    { file: "README.md", reason: "Repository overview — where the project explains its own purpose.", kind: "documentation" },
    { file: "lib/app.py", reason: "Discovered run entrypoint — a command in this repository actually runs this file.", kind: "entrypoint" },
  ],
  approvedKnowledge: [
    {
      id: "pk-1", knowledge: "Persistence mode is profile-selected.", whyItMatters: "Changes should preserve shared repository contracts.",
      appliesTo: ["lib/context/**"], lastVerified: "2026-03-01T00:00:00Z", stalenessFlag: "",
    },
  ],
  pendingKnowledge: [
    { id: "pk-draft-1", knowledge: "Document client test enforcement.", whyItMatters: "No CI invocation found for the local test suite.", appliesTo: ["client/**"], source: "system-prompted", draftReason: "3 workflow observations" },
  ],
  apiData: {
    routes: [
      { method: "GET", path: "/users/{id}", file: "app.py", line: 12, handler: "get_user", framework: "fastapi_or_flask", evidence: [] },
    ],
    entities: [
      {
        name: "Owner", file: "models.py", line: 5, tableName: null, language: "python",
        columns: [{ name: "id", type: "unknown", primaryKey: true }],
        columnsInferred: true,
        relationships: [{ field: "pets", targetEntity: "Pet", cardinality: "unknown" }],
        evidence: [],
      },
    ],
    persistenceSummary: { mode: "orm", entityCount: 1, byLanguage: { python: 1 } },
  },
  cicd: {
    workflows: [
      {
        name: "CI", provider: "github_actions", configFile: ".github/workflows/ci.yml", triggers: ["push"],
        jobs: [{ name: "test", runsOn: "ubuntu-latest", needs: [], commands: ["pytest"] }],
        evidence: [],
      },
    ],
    otherProvidersDetected: [],
  },
  runtimeConfig: {
    runtimes: [{ language: "python", version: "3.12-slim", sourceFile: "Dockerfile", evidence: [] }],
    frameworks: [{ name: "fastapi", version: null, sourceFile: "requirements.txt", evidence: [] }],
    configSources: [{ file: "Dockerfile", evidence: [] }],
    environmentVariables: [
      { name: "DATABASE_URL", sourceFile: ".env", looksSensitive: false, evidence: [] },
      { name: "OPENAI_API_KEY", sourceFile: ".env", looksSensitive: true, evidence: [] },
    ],
  },
  security: {
    secretIndicators: [
      { category: "declared_name", patternType: null, name: "OPENAI_API_KEY", file: ".env", line: null, redacted: true, evidence: [] },
      { category: "hardcoded_value_pattern", patternType: "aws_access_key_id", name: "AWS_KEY", file: "config.py", line: 4, redacted: true, evidence: [] },
    ],
    sensitiveConfiguration: [
      {
        category: "tls_verification_disabled", title: "TLS certificate verification appears to be disabled",
        description: "Code disabling TLS/SSL certificate verification was found, which allows man-in-the-middle attacks.",
        severity: "high", file: "client.py", line: 12, evidence: [],
      },
    ],
    authenticationIndicators: [
      { type: "dependency", name: "flask-login", file: "requirements.txt", line: null, evidence: [] },
    ],
    securityToolingDetected: [
      { name: "SECURITY.md", file: "SECURITY.md", evidence: [] },
    ],
  },
  changesHistory: {
    status: "COMPARED",
    previousSnapshot: { generatedAt: "2026-03-14T10:00:00Z", gitHead: "abc1111111", identityName: "speed", schemaVersion: 9 },
    currentSnapshot: { generatedAt: "2026-03-15T10:00:00Z", gitHead: "abc1234567", identityName: "speed", schemaVersion: 9 },
    summary: ["+1 domain", "-1 api route", "Runtime (python) changed from 3.11 to 3.12"],
    warnings: [],
    sections: [
      {
        key: "domains", label: "Domains", available: true, reason: null,
        added: [{ key: "cluster-ui", title: "Dashboard UI", evidence: [] }],
        removed: [], changed: [],
      },
      {
        key: "routes", label: "API routes", available: true, reason: null,
        added: [],
        removed: [{ key: "GET /old-endpoint", title: "GET /old-endpoint", evidence: [] }],
        changed: [],
      },
      {
        key: "runtimes", label: "Runtimes", available: true, reason: null,
        added: [], removed: [],
        changed: [{ key: "python", title: "python", fields: [{ field: "version", before: "3.11", after: "3.12" }], evidence: [] }],
      },
      {
        key: "cicd_workflows", label: "CI/CD workflows", available: false,
        reason: "not present in the previous digest — schema predates this section",
        added: [], removed: [], changed: [],
      },
    ],
  },
};

export const partialDigest: RepositoryDigestData = {
  ...baseDigest,
  status: "PARTIAL",
  footprint: { ...baseDigest.footprint, symbolCount: null, domainCount: null },
  domains: [],
  relationships: [],
  commands: [],
  conventions: [],
  warnings: [],
  readiness: [
    { capability: "semantic_graph", status: "UNAVAILABLE", reason: "semantic-graph.json does not exist", remediation: "Run the Layer 1 context build" },
  ],
  coverageStats: null,
  entrypoints: [],
  annotatedTree: [],
  readingPath: [],
  approvedKnowledge: [],
  pendingKnowledge: [],
  apiData: null,
  cicd: null,
  runtimeConfig: null,
  security: null,
  changesHistory: null,
};

export const staleDigest: RepositoryDigestData = {
  ...baseDigest,
  effectiveState: "STALE",
  freshness: { ...baseDigest.freshness, state: "STALE", currentGitHead: "def7654321", staleReasons: ["git_head"] },
};

export const baseStatus: RepositoryDigestBuildStatus = {
  state: "CURRENT",
  startedAt: null,
  completedAt: "2026-03-15T10:00:00Z",
  lastError: null,
  hasReadableDigest: true,
  hasProjectMap: true,
  indexedGitHead: "abc1234567",
  currentGitHead: "abc1234567",
  staleReasons: [],
};
