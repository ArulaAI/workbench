import { meta } from './_data';
import ReplayView from './_replay/ReplayView';

/* ── SVG Icons (GitHub Octicons, MIT) ──────────── */

const IconGitHub = () => (
  <svg className="cs-gh-icon" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
  </svg>
);

const IconStar = () => (
  <svg className="cs-gh-stat-icon" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
    <path d="M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25z"/>
  </svg>
);

const IconPeople = () => (
  <svg className="cs-gh-stat-icon" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
    <path d="M2 5.5a3.5 3.5 0 115.898 2.549 5.507 5.507 0 013.034 4.084.75.75 0 11-1.482.236 4.001 4.001 0 00-7.9 0 .75.75 0 01-1.482-.236A5.507 5.507 0 013.102 8.05 3.49 3.49 0 012 5.5zM11 4a.75.75 0 100 1.5 1.5 1.5 0 01.666 2.844.75.75 0 00-.416.672v.352a.75.75 0 00.574.73c1.2.289 2.162 1.2 2.522 2.372a.75.75 0 101.434-.44 5.01 5.01 0 00-2.56-3.012A3 3 0 0011 4z"/>
  </svg>
);

const IconCommit = () => (
  <svg className="cs-gh-stat-icon" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
    <path d="M11.93 8.5a4.002 4.002 0 01-7.86 0H.75a.75.75 0 010-1.5h3.32a4.002 4.002 0 017.86 0h3.32a.75.75 0 010 1.5h-3.32zM8 10.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z"/>
  </svg>
);

/* ── Language → CSS class mapping ──────────────── */

const LANG_KEY: Record<string, string> = {
  TypeScript: 'ts',
  PHP: 'php',
  Other: 'other',
};

export default function CaseStudyShell() {
  return (
    <div className="cs-shell">
      {/* ── Hero ────────────────────────────────── */}
      <section id="hero" className="cs-hero">
        <div className="cs-hero-kicker">Case Study</div>

        {/* ── GitHub Card ──────────────────────── */}
        <div className="cs-gh-card">
          <div className="cs-gh-header">
            <IconGitHub />
            <a
              href="https://github.com/appwrite/appwrite"
              className="cs-gh-name"
              target="_blank"
              rel="noopener noreferrer"
            >
              appwrite / appwrite
            </a>
          </div>

          <p className="cs-gh-desc">{meta.github.description}</p>

          {/* Language meter bar */}
          <div className="cs-gh-meter" aria-label="Language breakdown">
            {meta.codebase.languages.map((lang) => (
              <div
                key={lang.name}
                className={`cs-gh-meter-seg cs-gh-meter-${LANG_KEY[lang.name] ?? 'other'}`}
                style={{ width: `${lang.pct}%` }}
              />
            ))}
          </div>

          <div className="cs-gh-langs">
            {meta.codebase.languages.map((lang) => (
              <span key={lang.name} className="cs-gh-lang-item">
                <span className={`cs-dot cs-dot-${LANG_KEY[lang.name] ?? 'other'}`} />
                {lang.name} {lang.pct}%
              </span>
            ))}
          </div>

          {/* Stats row */}
          <div className="cs-gh-stats">
            <div className="cs-gh-stat">
              <div className="cs-gh-stat-top">
                <IconStar />
                <span className="cs-gh-stat-value">{meta.github.stars}</span>
              </div>
              <span className="cs-gh-stat-label">Stars</span>
            </div>
            <div className="cs-gh-divider" />
            <div className="cs-gh-stat">
              <div className="cs-gh-stat-top">
                <IconPeople />
                <span className="cs-gh-stat-value">{meta.github.contributors.toLocaleString()}</span>
              </div>
              <span className="cs-gh-stat-label">Contributors</span>
            </div>
            <div className="cs-gh-divider" />
            <div className="cs-gh-stat">
              <div className="cs-gh-stat-top">
                <IconCommit />
                <span className="cs-gh-stat-value">{meta.github.commits.toLocaleString()}</span>
              </div>
              <span className="cs-gh-stat-label">Commits</span>
            </div>
          </div>

          {/* Tech stack badges */}
          <div className="cs-gh-tech">
            <div className="cs-gh-tech-badges">
              <span className="cs-tech-badge cs-tech-ts">TS</span>
              <span className="cs-tech-badge cs-tech-php">PHP</span>
              <span className="cs-tech-badge cs-tech-mariadb">MariaDB</span>
              <span className="cs-tech-badge cs-tech-mongodb">MongoDB</span>
              <span className="cs-tech-badge cs-tech-pg">PostgreSQL</span>
            </div>
            <span className="cs-gh-tech-summary">
              {meta.platform.products.length} API products &middot;{' '}
              {meta.platform.sdks.length} SDKs &middot;{' '}
              {meta.platform.databases.length} databases
            </span>
          </div>
        </div>

        {/* ── Issue + Headline ─────────────────── */}
        <a
          href={`https://github.com/appwrite/appwrite/issues/${meta.github.issue}`}
          className="cs-hero-issue"
          target="_blank"
          rel="noopener noreferrer"
        >
          issue #{meta.github.issue} &middot; {meta.feature}
        </a>

        <h1 className="cs-hero-title">
          From open issue to a fix<br />
          <span className="cs-hero-accent">in under 2 hours.</span>
        </h1>

        {/* ── Metrics ──────────────────────────── */}
        <div className="cs-hero-metrics">
          <div className="cs-hm">
            <span className="cs-hm-value">7</span>
            <span className="cs-hm-label">files changed</span>
          </div>
          <div className="cs-hm-divider" />
          <div className="cs-hm">
            <span className="cs-hm-value">3/3</span>
            <span className="cs-hm-label">specs built</span>
          </div>
          <div className="cs-hm-divider" />
          <div className="cs-hm">
            <span className="cs-hm-value">3</span>
            <span className="cs-hm-label">bugs self-caught</span>
          </div>
          <div className="cs-hm-divider" />
          <div className="cs-hm">
            <span className="cs-hm-value">1</span>
            <span className="cs-hm-label">security resolve</span>
          </div>
          <div className="cs-hm-divider" />
          <div className="cs-hm">
            <span className="cs-hm-value">~200</span>
            <span className="cs-hm-label">lines of tests</span>
          </div>
        </div>

        <div className="cs-hero-scroll-hint">Watch the full run &#8595;</div>
      </section>

      {/* ── Replay ──────────────────────────────── */}
      <ReplayView />
    </div>
  );
}
