import { useStore } from '@nanostores/react';
import { $currentAct, nextAct, prevAct, ACTS } from '../../stores/replay';
import ActSpecAuthoring from './acts/ActSpecAuthoring';
import ActUnderstanding from './acts/ActUnderstanding';
import ActPipeline from './acts/ActPipeline';
import ActLearning from './acts/ActLearning';
import ActResult from './acts/ActResult';

const ACT_COMPONENTS: Record<string, React.FC> = {
  'spec-authoring': ActSpecAuthoring,
  'understanding': ActUnderstanding,
  'pipeline': ActPipeline,
  'learning': ActLearning,
  'result': ActResult,
};

export default function ReplayShell() {
  const currentAct = useStore($currentAct);
  const currentIdx = ACTS.findIndex((a) => a.id === currentAct);
  const act = ACTS[currentIdx];
  const Component = ACT_COMPONENTS[currentAct];

  return (
    <div className="replay-shell">
      <div className="act-header">
        <span className="act-header-number">Act {act.number}</span>
        <h2 className="act-header-title">{act.label}</h2>
        <p className="act-header-subtitle">{act.subtitle}</p>
      </div>

      <div className="act-content">
        <Component />
      </div>

      <div className="act-nav-buttons">
        {currentIdx > 0 && (
          <button className="act-btn act-btn-prev" onClick={prevAct}>
            <span className="act-btn-arrow">&larr;</span>
            Act {ACTS[currentIdx - 1].number}: {ACTS[currentIdx - 1].label}
          </button>
        )}
        {currentIdx < ACTS.length - 1 && (
          <button className="act-btn act-btn-next" onClick={nextAct}>
            Act {ACTS[currentIdx + 1].number}: {ACTS[currentIdx + 1].label}
            <span className="act-btn-arrow">&rarr;</span>
          </button>
        )}
      </div>
    </div>
  );
}
