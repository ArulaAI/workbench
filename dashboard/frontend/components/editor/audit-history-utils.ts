import type { AuditIssue, SpeedAuditResult } from '@/lib/graphql/queries/editor';

export function formatRelativeTime(isoString: string): string {
  if (!isoString) return 'unknown';

  const date = new Date(isoString);
  if (isNaN(date.getTime())) return 'unknown';

  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffMs / (1000 * 60));
  const diffHour = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDay = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffSec < 60) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;

  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(date);
}

export function issueKey(issue: AuditIssue): string {
  return `${issue.section}::${issue.message.slice(0, 80)}`;
}

export interface ComparisonResult {
  removed: AuditIssue[];
  unchanged: AuditIssue[];
  added: AuditIssue[];
}

export function computeComparison(olderAudit: SpeedAuditResult, newerAudit: SpeedAuditResult): ComparisonResult {
  const olderMap = new Map<string, AuditIssue>(olderAudit.issues.map(i => [issueKey(i), i]));
  const newerMap = new Map<string, AuditIssue>(newerAudit.issues.map(i => [issueKey(i), i]));

  const removed: AuditIssue[] = [];
  for (const [key, issue] of olderMap) {
    if (!newerMap.has(key)) removed.push(issue);
  }

  const added: AuditIssue[] = [];
  const unchanged: AuditIssue[] = [];
  for (const [key, issue] of newerMap) {
    if (olderMap.has(key)) {
      unchanged.push(issue);
    } else {
      added.push(issue);
    }
  }

  return { removed, unchanged, added };
}

export function getPersistentIssues(latestAudit: SpeedAuditResult, previousAudit: SpeedAuditResult | null): Set<string> {
  if (!previousAudit) return new Set();

  const latestKeys = new Set(latestAudit.issues.map(issueKey));
  const previousKeys = new Set(previousAudit.issues.map(issueKey));

  const intersection = new Set<string>();
  for (const key of latestKeys) {
    if (previousKeys.has(key)) intersection.add(key);
  }

  return intersection;
}
