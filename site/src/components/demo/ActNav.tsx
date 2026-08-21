import { useStore } from '@nanostores/react';
import { $currentAct, ACTS, goToAct, type ActId } from '../../stores/replay';

export default function ActNav() {
  const currentAct = useStore($currentAct);
  const currentIdx = ACTS.findIndex((a) => a.id === currentAct);

  return (
    <nav className="act-nav">
      <div className="act-nav-inner">
        {ACTS.map((act, i) => {
          const isActive = act.id === currentAct;
          const isPast = i < currentIdx;
          return (
            <button
              key={act.id}
              className={`act-tab ${isActive ? 'active' : ''} ${isPast ? 'past' : ''}`}
              onClick={() => goToAct(act.id)}
            >
              <span className="act-number">ACT {act.number}</span>
              <span className="act-label">{act.label}</span>
              {i < ACTS.length - 1 && <span className="act-connector" />}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
