// All data extracted from a real SPEED run on the Appwrite codebase (2026-03-26).
// Source: github.com/appwrite/appwrite, branch 1.9.x
// Feature: sort-auth-by-last-activity

export const meta = {
  project: 'Appwrite',
  github: {
    stars: '55K+',
    contributors: 451,
    commits: 33125,
    issue: 11480,
    description: 'Your backend, minus the hassle.',
  },
  codebase: {
    // From GitHub's linguist breakdown (screenshot verified)
    languages: [
      { name: 'TypeScript', pct: 64.4 },
      { name: 'PHP', pct: 34.2 },
      { name: 'Other', pct: 1.4 },
    ],
    testFiles: 275,
  },
  platform: {
    // From README.md product list
    products: ['Account', 'Users', 'Teams', 'Databases', 'Storage', 'Functions', 'Messaging', 'Realtime', 'Locale', 'Avatars', 'MCP', 'Sites'],
    // From README.md SDK list (client + server)
    sdks: ['Web', 'Flutter', 'Apple', 'Android', 'Node.js', 'PHP', 'Python', 'Dart', 'Deno', 'Ruby', 'Kotlin', 'Swift', '.NET', 'React Native'],
    // From docker-compose.yml (MariaDB, MongoDB, PostgreSQL)
    databases: ['MariaDB', 'MongoDB', 'PostgreSQL'],
  },
  feature: 'sort-auth-by-last-activity',
  startedAt: '2026-03-26T15:54:47Z',
  completedAt: '2026-03-26T18:01:00Z',
  branch: '1.9.x',
};

// ── Scene 1: Specs ──────────────────────────────────────────────

export const specs = {
  product: {
    filename: 'specs/product/sort-auth-by-last-activity.md',
    problem:
      'Developers building on Appwrite cannot sort or filter users by their last activity timestamp. The accessedAt field exists in the database with a proper index, but the Users API query validator doesn\'t expose it. Teams that need to identify inactive accounts, build admin dashboards, or run engagement analysis must implement custom tracking logic on their side.',
    personas: [
      { name: 'Team Lead', role: 'Admin dashboard builder', useCase: 'See which users are active vs. dormant without pulling entire user list' },
      { name: 'Data Analyst', role: 'Product team', useCase: 'Query users inactive 30+ days for re-engagement campaigns' },
      { name: 'SaaS Developer', role: 'Multi-tenant maintainer', useCase: 'Prune or flag accounts with no activity since a given date' },
    ],
    userStories: [
      { id: 'ST1', story: 'List users sorted by most recent activity', query: "Query::orderDesc('accessedAt')", priority: 'Must' },
      { id: 'ST2', story: 'List users sorted by oldest activity first', query: "Query::orderAsc('accessedAt')", priority: 'Must' },
      { id: 'ST3', story: 'Filter users inactive since a date', query: "Query::lessThan('accessedAt', ...)", priority: 'Must' },
      { id: 'ST4', story: 'Filter users active after a date', query: "Query::greaterThan('accessedAt', ...)", priority: 'Should' },
    ],
    scopeOut: [
      'Changing accessedAt update frequency (24h throttle)',
      'Adding lastSeenAt or lastActivityAt aliases',
      'Console UI changes',
      'Real-time activity tracking (WebSocket presence)',
    ],
  },
  design: {
    filename: 'specs/design/sort-auth-by-last-activity.md',
    intent: 'Invisible infrastructure. The user experiences this through existing query patterns, not new screens. The API should feel like accessedAt was always sortable.',
    doNot: [
      'Introduce new query syntax specific to activity sorting',
      'Create a separate "active users" view or endpoint',
      'Add visual indicators at the API level (Console concern)',
    ],
    states: [
      { name: 'Empty', description: '{ users: [], total: 0 } when no users match' },
      { name: 'Populated', description: 'Users with accessedAt in requested order' },
      { name: 'Null accessedAt', description: 'Pre-V19 users: empty string, sort to boundary' },
      { name: 'Error', description: '400 with GENERAL_QUERY_INVALID for invalid attributes' },
    ],
    notes: [
      'accessedAt is not real-time presence. Updates at most once per 24h (APP_USER_ACCESS constant).',
      'Impersonation exclusion: admin impersonation does not update accessedAt.',
      'Index _key_accessedAt already exists from Migration V19. No CREATE INDEX needed.',
    ],
  },
  tech: {
    filename: 'specs/tech/sort-auth-by-last-activity.md',
    queryTypes: [
      { type: 'orderAsc', example: "Query::orderAsc('accessedAt')" },
      { type: 'orderDesc', example: "Query::orderDesc('accessedAt')" },
      { type: 'greaterThan', example: "Query::greaterThan('accessedAt', datetime)" },
      { type: 'lessThan', example: "Query::lessThan('accessedAt', datetime)" },
      { type: 'between', example: "Query::between('accessedAt', start, end)" },
      { type: 'isNull', example: "Query::isNull('accessedAt')" },
      { type: 'isNotNull', example: "Query::isNotNull('accessedAt')" },
    ],
    fileImpact: [
      { file: 'src/Appwrite/Utopia/Database/Validator/Queries/Users.php', change: "Add 'accessedAt' to ALLOWED_ATTRIBUTES" },
      { file: 'tests/unit/Utopia/Database/Validator/Queries/UsersTest.php', change: 'Unit tests for accessedAt query validation' },
      { file: 'tests/e2e/Services/Users/UsersBase.php', change: 'E2E tests for sort and filter behavior' },
      { file: 'docs/references/users/list-users.md', change: 'Document accessedAt as sortable/filterable' },
    ],
    keyDecisions: [
      { decision: 'Expose existing accessedAt vs. add new field', choice: 'Expose existing', rationale: 'Already exists, is indexed, and is in the API response' },
      { decision: 'Validator-only change vs. new endpoint', choice: 'Modify validator allow-list', rationale: 'Existing query system handles this. New endpoint breaks consistent API pattern' },
      { decision: 'Migration required?', choice: 'No', rationale: 'V19 already added attribute and index' },
    ],
  },
};

// ── Scene 2: Execute ────────────────────────────────────────────

export const planAudits = [
  { specType: 'tech', status: 'pass', estimatedTasks: 2, recommendation: 'ok' },
  { specType: 'product', status: 'pass', estimatedTasks: 4, recommendation: 'ok' },
  { specType: 'design', status: 'pass', estimatedTasks: null, recommendation: null },
];

export const validationFindings = [
  { severity: 'note', issue: 'PR #11552 already implemented the core change. Task 1 should check if accessedAt is already present before modifying.' },
  { severity: 'note', issue: 'Product spec lists docs as in-scope but doesn\'t specify the file path. Tech spec identifies docs/references/users/list-users.md but existence is unconfirmed.' },
  { severity: 'note', issue: 'E2E tests require distinct accessedAt timestamps, but accessedAt is throttled to 24h. Test fixtures need workaround.' },
  { severity: 'warning', issue: 'Design spec defines Console Integration Contract but product spec marks Console UI as out of scope.' },
];

export const tasks = [
  {
    id: '1',
    title: 'Add accessedAt to Users query validator and unit tests',
    dependsOn: [] as string[],
    files: ['src/Appwrite/Utopia/Database/Validator/Queries/Users.php', 'tests/unit/Utopia/Database/Validator/Queries/UsersTest.php'],
    model: 'sonnet',
    duration: 42,
    gates: { passed: 8, warned: 2, failed: 0, total: 10 },
    gateChecks: [
      { name: 'diff_non_empty', status: 'pass' },
      { name: 'declared_files', status: 'pass' },
      { name: 'scope', status: 'pass' },
      { name: 'python_imports', status: 'pass' },
      { name: 'not_blocked', status: 'pass' },
      { name: 'test_coverage', status: 'pass' },
      { name: 'gate_evidence', status: 'warn' },
      { name: 'criteria', status: 'warn' },
      { name: 'secrets', status: 'pass' },
      { name: 'syntax', status: 'pass' },
    ],
    decisions: ['Both files already contained the required changes from baseline commit (583799a9f0). No additional modifications needed.'],
    budget: { total: 60000, used: 1814, codeUsed: 786, taskUsed: 985, specUsed: 43 },
  },
  {
    id: '2',
    title: 'Add E2E tests for accessedAt sort and filter on Users API',
    dependsOn: ['1'],
    files: ['tests/e2e/Services/Users/UsersBase.php'],
    model: 'sonnet',
    duration: 384,
    gates: { passed: 8, warned: 2, failed: 0, total: 10 },
    gateChecks: [
      { name: 'diff_non_empty', status: 'pass' },
      { name: 'declared_files', status: 'pass' },
      { name: 'scope', status: 'pass' },
      { name: 'python_imports', status: 'pass' },
      { name: 'not_blocked', status: 'pass' },
      { name: 'test_coverage', status: 'pass' },
      { name: 'gate_evidence', status: 'warn' },
      { name: 'criteria', status: 'warn' },
      { name: 'secrets', status: 'pass' },
      { name: 'syntax', status: 'pass' },
    ],
    decisions: [
      'Used uniqid() suffix in email addresses to ensure fresh users on each test run.',
      'Used sleep(1) between session creations for distinct second-precision timestamps.',
      'Used limit(100) on ordering tests so all created users are in the result page.',
    ],
    budget: { total: 60000, used: 29004, codeUsed: 28791, taskUsed: 170, specUsed: 43 },
  },
  {
    id: '3',
    title: 'Document accessedAt as queryable attribute on Users list endpoint',
    dependsOn: ['1'],
    files: ['docs/references/users/list-users.md'],
    model: 'sonnet',
    duration: 67,
    gates: { passed: 8, warned: 2, failed: 0, total: 10 },
    gateChecks: [
      { name: 'diff_non_empty', status: 'pass' },
      { name: 'declared_files', status: 'pass' },
      { name: 'scope', status: 'pass' },
      { name: 'python_imports', status: 'pass' },
      { name: 'not_blocked', status: 'pass' },
      { name: 'test_coverage', status: 'pass' },
      { name: 'gate_evidence', status: 'warn' },
      { name: 'criteria', status: 'warn' },
      { name: 'secrets', status: 'pass' },
      { name: 'syntax', status: 'pass' },
    ],
    decisions: [],
    budget: { total: 60000, used: 4200, codeUsed: 3100, taskUsed: 850, specUsed: 250 },
  },
  {
    id: '4',
    title: 'Fix coherence issues',
    dependsOn: ['2'],
    files: ['app/controllers/shared/api.php', 'app/init/constants.php', 'tests/e2e/Services/Users/UsersBase.php'],
    model: 'sonnet',
    duration: 155,
    gates: { passed: 8, warned: 2, failed: 0, total: 10 },
    gateChecks: [
      { name: 'diff_non_empty', status: 'pass' },
      { name: 'declared_files', status: 'pass' },
      { name: 'scope', status: 'pass' },
      { name: 'python_imports', status: 'pass' },
      { name: 'not_blocked', status: 'pass' },
      { name: 'test_coverage', status: 'pass' },
      { name: 'gate_evidence', status: 'warn' },
      { name: 'criteria', status: 'warn' },
      { name: 'secrets', status: 'pass' },
      { name: 'syntax', status: 'pass' },
    ],
    decisions: [
      'Explained api.php/constants.php no-change rationale in the setupAccessedAtUsers() docblock.',
      'Used descriptive assertion messages on GET /account calls for fail-fast diagnostics.',
    ],
    budget: { total: 60000, used: 12500, codeUsed: 10200, taskUsed: 1800, specUsed: 500 },
  },
];

// ── Scene 3: Judge ──────────────────────────────────────────────

export const reviews = [
  {
    taskId: '1',
    verdict: 'approve' as const,
    specChecks: { satisfied: 10, partial: 0, failed: 0, total: 10 },
    issues: [],
    strengths: [
      'Change is minimal and precisely scoped: 1 line in source, 7 lines in test.',
      'Test coverage is comprehensive: both sort directions, range comparisons, null checks.',
      'Timestamp format uses ISO 8601 with timezone, consistent with Appwrite datetime values.',
      'No unrelated formatting, refactoring, or comment changes.',
    ],
  },
  {
    taskId: '2',
    verdict: 'approve' as const,
    specChecks: { satisfied: 7, partial: 1, failed: 0, total: 8 },
    issues: [
      { severity: 'major', file: 'tests/e2e/Services/Users/UsersBase.php', line: 2762, message: 'Unverified that POST /users/{userId}/sessions actually updates accessedAt. May need a real auth login via /account/sessions/email.' },
      { severity: 'minor', file: 'tests/e2e/Services/Users/UsersBase.php', line: 2892, message: 'Test 6 cannot verify sort order because only one user survives the greaterThan filter.' },
      { severity: 'nit', file: 'tests/e2e/Services/Users/UsersBase.php', line: 2802, message: 'assertLessThan compares ISO 8601 strings lexicographically. Works for UTC but implicit assumption.' },
      { severity: 'nit', file: 'tests/e2e/Services/Users/UsersBase.php', line: 2776, message: 'sleep(1) makes test suite 1 second slower per run. Necessary for second-level precision.' },
    ],
    strengths: [
      'Self-validating setup: assertNotEmpty guards against silent false positives.',
      'uniqid() prefix prevents test data collisions across parallel runs.',
      'All relative-position assertions use correct PHPUnit assertLessThan semantics.',
      'noActivityUser correctly validated to have empty accessedAt at creation.',
      'Far-future timestamp (2099) is robust against flakiness.',
    ],
  },
  {
    taskId: '3',
    verdict: 'request_changes' as const,
    specChecks: { satisfied: 4, partial: 1, failed: 0, total: 6 },
    issues: [
      {
        severity: 'major',
        file: 'docs/references/users/list-users.md',
        line: 45,
        message: "APP_USER_ACCESS described as 'environment variable' but it is a hardcoded PHP constant (app/init/constants.php:44). There is no env var operators can set. Current text will send operators on a wild goose chase.",
        suggestion: "Remove env-var attribution. Write: 'accessedAt updates at most once per 24 hours per user. High-frequency logins within the same 24-hour window will not produce additional updates.'",
      },
      {
        severity: 'minor',
        file: 'docs/references/users/list-users.md',
        line: 47,
        message: "Note says 'impersonator flag is set' but impersonator (boolean) means 'this user CAN impersonate others'. The actual guard checks impersonatorUserId (whether someone IS impersonating right now). Different attributes.",
        suggestion: "Rewrite to: 'Requests where another user is impersonating this account (indicated by a non-empty impersonatorUserId on the session) do not update accessedAt.'",
      },
      {
        severity: 'nit',
        file: 'docs/references/users/list-users.md',
        line: 28,
        message: 'PHP code examples use $client->users->list() which is not the PHP SDK pattern. Requires service instantiation: $users = new Users($client);',
      },
    ],
    strengths: [
      'All six acceptance criteria satisfied cleanly.',
      '24-hour throttle documentation is factually accurate.',
      'Three code examples included (sort, filter, combined).',
      'NULL sort order note is clear and correct.',
      'accessedAt positioned consistently with other datetime attributes in table.',
    ],
  },
  {
    taskId: '4',
    verdict: 'approve' as const,
    specChecks: { satisfied: 2, partial: 2, failed: 0, total: 4 },
    issues: [
      { severity: 'major', file: 'tests/e2e/Services/Users/UsersBase.php', line: 2772, message: 'GET /account calls that trigger accessedAt middleware have no assertions on response. Silent failure will cause misleading test errors later.' },
      { severity: 'minor', file: 'tests/e2e/Services/Users/UsersBase.php', line: 2801, message: 'assertEmpty for noActivityUser accessedAt was removed. Regression in this invariant would go undetected.' },
    ],
    strengths: [
      'Core coherence fix is correct: creating a session does NOT update accessedAt. Only authenticated requests through api.php middleware do.',
      'Splitting monolithic test into 4 focused methods improves debuggability.',
      'Per-project static cache in setupAccessedAtUsers() avoids redundant user creation.',
      '1-second sleep correctly placed between authenticated requests, not session creations.',
    ],
  },
];

// ── Security scanner finding ────────────────────────────────────

export const secretsScan = {
  result: 'false_positive',
  file: 'tests/e2e/Services/Users/UsersBase.php',
  flaggedLines: [137, 149, 176, 408],
  flaggedContent: 'Pre-existing test fixtures: argon2 hashes, scrypt keys, signing keys',
  diagnosis: 'The gate failure is a secret scanner false positive. UsersBase.php contains pre-existing test fixtures that were present before this task\'s diff. The scanner flagged those lines, none of which are inside the new test method. The diff introduces no new secrets.',
  resolution: 'Added tests/e2e/** to secrets_exclude in speed.toml',
  configChange: 'secrets_exclude = [".env*", "*.example", "tests/fixtures/**", "tests/e2e/**"]',
};

// ── Guardian findings ───────────────────────────────────────────

export const guardianPostReview = {
  status: 'aligned',
  flags: [
    {
      severity: 'critical' as const,
      description: 'Product vision document is a blank template. Every section contains placeholder text. Guardian evaluation requires a populated vision document. Without one, this check produces no meaningful signal, which is itself a risk.',
    },
    {
      severity: 'note' as const,
      description: "The impersonation note silently introduces a security/privacy policy decision in documentation without a visible product decision record. This may be correct, but edge-case rules can surprise API consumers.",
    },
  ],
};

export const guardianPostIntegration = {
  status: 'flagged',
  flags: [
    {
      severity: 'critical' as const,
      description: 'Product vision document is an unfilled template. Guardian check cannot produce a valid verdict. Populate the vision document and re-run.',
    },
    {
      severity: 'note' as const,
      description: 'From AGENTS.md, Appwrite is a self-hosted BaaS. The feature (exposing accessedAt as queryable) is consistent with BaaS API primitives: no new surface, no new dependencies, no schema changes.',
    },
  ],
};

// ── Scene 4: Correct ────────────────────────────────────────────

export const task3Fixes = [
  { what: 'Removed "environment variable" claim', detail: 'APP_USER_ACCESS is a hardcoded PHP constant, not an env var operators can configure.' },
  { what: 'Fixed impersonator terminology', detail: 'Replaced impersonator flag reference with impersonatorUserId on the request context.' },
  { what: 'Fixed PHP SDK syntax', detail: 'Replaced $client->users->list() with correct instantiation: $users = new Users($client);' },
];

export const coherenceCreatedTask4 = {
  reason: 'E2E tests create sessions via admin endpoint (POST /users/{userId}/sessions) but never make an authenticated request AS the user. The api.php middleware at line 389 only updates accessedAt on authenticated user requests, not admin session creation. Tests would pass with empty accessedAt values.',
  fixes: [
    'Added GET /account calls with x-appwrite-session headers to trigger accessedAt middleware',
    'Split monolithic testAccessedAtSortAndFilter into 4 focused test methods',
    'Added per-project static cache to avoid redundant user creation across tests',
    'Positioned sleep(1) between authenticated requests for distinct timestamps',
  ],
};

// ── Scene 5: Verify ─────────────────────────────────────────────

export const coherence = {
  status: 'pass',
  contractGaps: [
    { item: 'Users Query Validator: accessedAt in allowed attributes', status: 'satisfied' },
    { item: 'Unit Tests: orderAsc, orderDesc, greaterThan, lessThan', status: 'satisfied' },
    { item: 'E2E Tests: sortDesc, sortAsc, filterLessThan, filterGreaterThan', status: 'satisfied' },
    { item: 'Documentation: accessedAt listed as queryable attribute', status: 'satisfied' },
    { item: 'Core query: list users sorted by most recent activity', status: 'satisfied' },
    { item: 'Core query: filter users inactive since a date', status: 'satisfied' },
    { item: 'Core query: filter users active after a date', status: 'satisfied' },
  ],
  schemaInconsistencies: [
    { description: 'accessedAt docs omit equal and notEqual while other datetime attributes include them. Validator accepts them.', severity: 'minor' },
  ],
};

export const integration = {
  mergedBranches: [
    'speed/sort-auth-by-last-activity/task-3-document-accessedat-as-queryable-attribu',
    'speed/sort-auth-by-last-activity/task-4-fix-coherence-issues',
  ],
  conflicts: 0,
  failures: 0,
  targetBranch: '1.9.x',
};

export const traceability = {
  requirementsFound: 5,
  coverageRatio: 1.0,
  covered: [
    { requirement: 'All existing Users list queries continue to work identically.', section: 'Acceptance Criteria', coveredBy: ['1', '2', '3'] },
    { requirement: 'Null accessedAt: must not throw; sort to boundary of result set.', section: 'Edge Cases', coveredBy: ['1', '2', '3', '4'] },
    { requirement: 'Future datetime filter: return empty set, not error.', section: 'Edge Cases', coveredBy: ['1', '2', '3', '4'] },
    { requirement: 'Empty user collection: return { users: [], total: 0 }.', section: 'Edge Cases', coveredBy: ['2', '3', '4'] },
    { requirement: 'NULL handling: pre-V19 users with NULL accessedAt. MariaDB sorts NULLs predictably.', section: 'Drawbacks', coveredBy: ['1', '2', '3', '4'] },
  ],
  uncovered: [],
};

// ── Scene 6: Learn ──────────────────────────────────────────────

export const observations = {
  total: 47,
  categories: [
    { type: 'agent_concern', count: 7, example: 'Gate evidence warning is a tooling artifact when changes are pre-committed.' },
    { type: 'reviewer_finding', count: 28, example: 'APP_USER_ACCESS is not an environment variable. Hardcoded PHP constant at constants.php:44.' },
    { type: 'guardian_verdict', count: 2, example: 'Vision document is blank template. Guardian check produces no meaningful signal.' },
    { type: 'coherence_issue', count: 2, example: 'accessedAt docs missing equal/notEqual while other datetime attributes include them.' },
    { type: 'security_finding', count: 4, example: 'Design spec defines Console contract but product spec excludes Console UI.' },
    { type: 'success', count: 1, example: 'Task 1: 2 files planned, 2 actual, 0 retries, 42 seconds.' },
  ],
  highlights: [
    {
      type: 'reviewer_finding',
      severity: 'major',
      finding: 'APP_USER_ACCESS described as environment variable but is hardcoded PHP constant. Would have sent operators searching for a non-existent env var.',
      taskId: '3',
    },
    {
      type: 'reviewer_finding',
      severity: 'major',
      finding: 'POST /users/{userId}/sessions does not trigger accessedAt middleware. Only client-side authenticated requests (using session secret) through api.php update the field.',
      taskId: '2',
    },
    {
      type: 'guardian_verdict',
      severity: 'note',
      finding: 'Impersonation behavioral note silently introduces security/privacy policy without product decision record.',
      taskId: '3',
    },
    {
      type: 'coherence_issue',
      severity: 'minor',
      finding: 'impersonator (admin capability flag) confused with impersonatorUserId (session-level impersonation indicator). Different attributes on the user document.',
      taskId: '3',
    },
  ],
};

export const conventions = {
  total: 438,
  filesAnalyzed: 1648,
  examples: [
    { convention: 'Always modify specs/design and specs/product together.', confidence: 'emerging', adherence: 1.0 },
    { convention: 'Always modify docs/references/documentsdb/create-operations.md and create-transaction.md together.', confidence: 'emerging', adherence: 1.0 },
    { convention: 'Always modify docs/references/vectorsdb/create-collection.md and create-document.md together.', confidence: 'emerging', adherence: 1.0 },
  ],
};

// ── Review nits (carried forward) ───────────────────────────────

export const reviewNits = [
  {
    severity: 'minor',
    file: 'tests/e2e/Services/Users/UsersBase.php',
    line: 2857,
    message: 'assertNotEmpty checks placed only in testAccessedAtSortDesc, not in setupAccessedAtUsers. If test execution order changes, empty accessedAt values will cause confusing failures.',
    taskId: '4',
  },
  {
    severity: 'nit',
    file: 'tests/e2e/Services/Users/UsersBase.php',
    line: 2809,
    message: 'Non-obvious that same $response/$userIds variable is reused for noActivityUser assertion. A short inline comment would help.',
    taskId: '4',
  },
];
