import data from '../../../data/f10-replay.json';

export default function ActResult() {
  const stats = data.result.stats;
  const chain = data.result.provenance_chain;

  return (
    <div className="act-result">
      {/* Before / After */}
      <div className="panel surface">
        <div className="panel-label">Before / After</div>
        <div className="result-before-after">
          {/* Before: flat event cards */}
          <div className="result-ba-col">
            <div className="ba-label">Before</div>
            <div className="feed-before">
              <div className="feed-before-card">
                <div className="feed-before-badge">SHIPPED</div>
                <div className="feed-before-time">1d ago</div>
                <div className="feed-before-title">Shipped AI Resume Builder</div>
                <div className="feed-before-id">project / 01KJJ0QT...</div>
              </div>
              <div className="feed-before-card">
                <div className="feed-before-badge">CREATED</div>
                <div className="feed-before-time">3d ago</div>
                <div className="feed-before-title">Created Hospitality OS</div>
                <div className="feed-before-id">tribe / 01KHH9RT...</div>
              </div>
              <div className="feed-before-card">
                <div className="feed-before-badge">JOINED</div>
                <div className="feed-before-time">3d ago</div>
                <div className="feed-before-title">Member joined tribe</div>
                <div className="feed-before-id">member / 01KHH9...</div>
              </div>
            </div>
          </div>

          <div className="result-ba-arrow">→</div>

          {/* After: rich timeline */}
          <div className="result-ba-col">
            <div className="ba-label">After</div>
            <div className="feed-after">
              {/* Milestone card */}
              <div className="feed-after-entry">
                <div className="feed-after-thread">
                  <div className="feed-after-avatar">MC</div>
                  <div className="feed-after-line" />
                </div>
                <div className="feed-after-body">
                  <div className="feed-after-meta">
                    <span className="feed-after-actor">Maya Chen</span>
                    <span className="feed-after-verb">shipped</span>
                    <span className="feed-after-time">2h ago</span>
                  </div>
                  <div className="feed-milestone">
                    <div className="feed-milestone-gradient" />
                    <div className="feed-milestone-body">
                      <div className="feed-milestone-title">AI Resume Builder</div>
                      <div className="feed-milestone-stack">React · Python · OpenAI · PostgreSQL</div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Content card */}
              <div className="feed-after-entry">
                <div className="feed-after-thread">
                  <div className="feed-after-avatar">TN</div>
                  <div className="feed-after-line" />
                </div>
                <div className="feed-after-body">
                  <div className="feed-after-meta">
                    <span className="feed-after-actor">Tom Nakamura</span>
                    <span className="feed-after-verb">formed a tribe</span>
                    <span className="feed-after-time">6h ago</span>
                  </div>
                  <div className="feed-content-card">
                    <div className="feed-content-title">Hospitality OS</div>
                    <div className="feed-content-desc">Building the operating system for independent hotels</div>
                  </div>
                </div>
              </div>

              {/* Activity line */}
              <div className="feed-after-entry feed-after-compact">
                <div className="feed-after-thread">
                  <div className="feed-after-avatar feed-after-avatar-sm">JO</div>
                </div>
                <div className="feed-after-body">
                  <div className="feed-after-meta">
                    <span className="feed-after-actor">James Okafor</span>
                    <span className="feed-after-verb">joined Hospitality OS</span>
                    <span className="feed-after-time">12h ago</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Stats bar */}
      <div className="panel surface">
        <div className="panel-label">By the Numbers</div>
        <div className="result-stats">
          <div className="result-stat">
            <span className="result-stat-value">{stats.specs_authored}</span>
            <span className="result-stat-label">Specs authored</span>
            <span className="result-stat-detail">{stats.spec_time}</span>
          </div>
          <div className="result-stat">
            <span className="result-stat-value">{stats.tasks_executed}</span>
            <span className="result-stat-label">Tasks executed</span>
            <span className="result-stat-detail">in parallel</span>
          </div>
          <div className="result-stat">
            <span className="result-stat-value">{stats.files_changed}</span>
            <span className="result-stat-label">Files changed</span>
            <span className="result-stat-detail">frontend + backend</span>
          </div>
          <div className="result-stat">
            <span className="result-stat-value">{stats.tests_written}</span>
            <span className="result-stat-label">Tests written</span>
            <span className="result-stat-detail">all passing</span>
          </div>
          <div className="result-stat">
            <span className="result-stat-value">{stats.spec_requirements_verified}</span>
            <span className="result-stat-label">Requirements verified</span>
            <span className="result-stat-detail">by reviewer</span>
          </div>
          <div className="result-stat">
            <span className="result-stat-value accent-text">{stats.vision_conflicts_flagged}</span>
            <span className="result-stat-label">Vision conflict flagged</span>
            <span className="result-stat-detail">by Guardian</span>
          </div>
        </div>
        <div className="result-total">
          <span className="result-total-label">Total wall-clock</span>
          <span className="result-total-value">{stats.total_wall_clock}</span>
        </div>
      </div>

      {/* Provenance chain */}
      <div className="panel surface">
        <div className="panel-label">Provenance Chain for {chain.requirement}</div>
        <p className="panel-note">
          Click any link to trace it back. Eight artifacts, each traceable, each backed by real data.
        </p>
        <div className="provenance-chain">
          {chain.links.map((link, i) => (
            <div key={i} className="provenance-link">
              <div className="provenance-dot" />
              {i < chain.links.length - 1 && <div className="provenance-line" />}
              <div className="provenance-content">
                <span className="provenance-phase">{link.phase}</span>
                <span className="provenance-text">{link.content}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Token burn / cost */}
      <div className="panel surface">
        <div className="panel-label">Token Burn</div>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr><th>Agent</th><th>Model</th><th>Input</th><th>Output</th><th>Cost</th></tr>
            </thead>
            <tbody>
              {data.result.token_burn.tasks.map((t) => (
                <tr key={t.label}>
                  <td>{t.label}</td>
                  <td className="mono small">{t.model}</td>
                  <td className="mono small">{(t.input_tokens / 1000).toFixed(0)}K</td>
                  <td className="mono small">{(t.output_tokens / 1000).toFixed(1)}K</td>
                  <td className="mono small">${t.cost.toFixed(2)}</td>
                </tr>
              ))}
              {data.result.token_burn.agents.map((a) => (
                <tr key={a.label}>
                  <td>{a.label}</td>
                  <td className="mono small">opus</td>
                  <td className="mono small">{(a.input_tokens / 1000).toFixed(0)}K</td>
                  <td className="mono small">{(a.output_tokens / 1000).toFixed(1)}K</td>
                  <td className="mono small">${a.cost.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="cost-summary">
          <div className="cost-summary-row">
            <span className="cost-summary-label">Total tokens</span>
            <span className="cost-summary-value mono">
              {(data.result.token_burn.total_input_tokens / 1000).toFixed(0)}K in · {(data.result.token_burn.total_output_tokens / 1000).toFixed(1)}K out
            </span>
          </div>
          <div className="cost-summary-row cost-summary-total">
            <span className="cost-summary-label">Feature cost</span>
            <span className="cost-summary-value cost-hero mono">${data.result.token_burn.total_cost.toFixed(2)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
