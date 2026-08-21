import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { useStore } from '@nanostores/react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  $visibleSteps, $currentStep,
  $activeFile, $phase, $phaseRanges,
  nextStep, prevStep, playPhase,
} from './store';
import type { TerminalLine, FileContent, Phase } from './steps';

/* ── Phase metadata ──────────────────────────── */

const PHASES: Phase[] = ['define', 'audit', 'execute', 'review', 'correct', 'coherence', 'integrate', 'learn'];

const PHASE_META: Record<Phase, { label: string; action: string }> = {
  define:    { label: 'Define',     action: 'Write Specs' },
  audit:     { label: 'Audit',      action: 'Run Audit' },
  execute:   { label: 'Execute',    action: 'Execute Tasks' },
  review:    { label: 'Review',     action: 'Review Code' },
  correct:   { label: 'Correct',    action: 'Self-Correct' },
  coherence: { label: 'Coherence',  action: 'Check Coherence' },
  integrate: { label: 'Integrate',  action: 'Integrate' },
  learn:     { label: 'Learn',      action: 'Wrap Up' },
};

/* ── File tree types & builder ───────────────── */

interface TreeNode {
  name: string;
  fullPath: string;
  type: 'file' | 'folder';
  children: TreeNode[];
  file?: FileContent;
}

type RawNode = { children: Map<string, RawNode>; isFile: boolean; file?: FileContent };

function buildFileTree(files: FileContent[]): TreeNode[] {
  const root: Map<string, RawNode> = new Map();

  for (const f of files) {
    const parts = f.path.split('/');
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      if (!current.has(part)) {
        current.set(part, { children: new Map(), isFile: false });
      }
      const node = current.get(part)!;
      if (i === parts.length - 1) {
        node.isFile = true;
        node.file = f;
      }
      current = node.children;
    }
  }

  function convert(map: Map<string, RawNode>, prefix: string): TreeNode[] {
    const nodes: TreeNode[] = [];
    for (const [key, val] of map) {
      if (val.isFile) {
        nodes.push({ name: key, fullPath: prefix + key, type: 'file', children: [], file: val.file });
      } else {
        let collapsed = key;
        let cur = val.children;
        let fp = prefix + key;
        while (cur.size === 1) {
          const [ck, cv] = [...cur.entries()][0];
          if (cv.isFile) break;
          collapsed += ' / ' + ck;
          fp += '/' + ck;
          cur = cv.children;
        }
        nodes.push({
          name: collapsed,
          fullPath: fp,
          type: 'folder',
          children: convert(cur, fp + '/'),
        });
      }
    }
    return nodes.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }

  return convert(root, '');
}

function dotClass(name: string): string {
  if (name.endsWith('.md')) return 'ws-dot-md';
  if (name.endsWith('.php')) return 'ws-dot-php';
  if (name.endsWith('.ts') || name.endsWith('.tsx')) return 'ws-dot-ts';
  return 'ws-dot-default';
}

/* ── Tour steps ──────────────────────────────── */

type Placement = 'bottom' | 'top' | 'right';

interface TourDef {
  target: string;
  title: string;
  body: string;
  placement: Placement;
}

const TOUR: TourDef[] = [
  {
    target: '.ws-phases',
    title: 'Drive the pipeline',
    body: 'Each button advances one phase of SPEED\'s run on Appwrite #11480. Click them left to right.',
    placement: 'bottom',
  },
  {
    target: '.ws-sidebar',
    title: 'File tree',
    body: 'Specs, source files, and tests appear here as SPEED creates them.',
    placement: 'right',
  },
  {
    target: '.ws-editor',
    title: 'Code & annotations',
    body: 'File contents with highlights. Review findings render as annotated cards.',
    placement: 'bottom',
  },
  {
    target: '.ws-terminal',
    title: 'Pipeline log',
    body: 'Commands, gate checks, and audit results.',
    placement: 'top',
  },
  {
    target: '.ws-phase-current',
    title: 'Ready?',
    body: 'Click to start the pipeline.',
    placement: 'bottom',
  },
];

/* ═══════════════════════════════════════════════
   Main Workspace
   ═══════════════════════════════════════════════ */

export default function ReplayView() {
  const currentStep = useStore($currentStep);
  const activeFile  = useStore($activeFile);
  const visibleSteps = useStore($visibleSteps);

  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [manualFile, setManualFile] = useState<FileContent | null>(null);

  // Tour state — check localStorage to skip on repeat visits
  const [tourStep, setTourStep] = useState<number>(() => {
    try { return localStorage.getItem('speed-cs-tour') ? -1 : 0; }
    catch { return 0; }
  });
  const tourActive = tourStep >= 0 && tourStep < TOUR.length;
  const tourActiveRef = useRef(tourActive);
  tourActiveRef.current = tourActive;

  const dismissTour = useCallback(() => {
    setTourStep(-1);
    try { localStorage.setItem('speed-cs-tour', '1'); } catch { /* noop */ }
  }, []);

  const displayFile = manualFile ?? activeFile;

  // Clear manual file when replay advances
  useEffect(() => { setManualFile(null); }, [currentStep]);

  // Visible files: deduplicated by path, most-recent content, first-seen order
  const visibleFiles = useMemo(() => {
    const map = new Map<string, FileContent>();
    const order: string[] = [];
    for (const step of visibleSteps) {
      if (step.file) {
        if (!map.has(step.file.path)) order.push(step.file.path);
        map.set(step.file.path, step.file);
      }
    }
    return order.map(p => map.get(p)!);
  }, [visibleSteps]);

  const tree = useMemo(() => buildFileTree(visibleFiles), [visibleFiles]);

  // Keyboard controls (disabled during tour)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (tourActiveRef.current) return;
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === 'ArrowRight') { e.preventDefault(); nextStep(); }
      if (e.key === 'ArrowLeft')  { e.preventDefault(); prevStep(); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const onToggleFolder = useCallback((path: string) => {
    setCollapsedFolders(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }, []);

  const onSelectFile = useCallback((file: FileContent) => {
    setManualFile(file);
  }, []);

  return (
    <div className="ws">
      {tourActive && (
        <Joyride
          step={tourStep}
          onNext={() => setTourStep(s => s + 1)}
          onDismiss={dismissTour}
        />
      )}
      <div className="ws-titlebar">
        <div className="ws-titlebar-dots">
          <span className="ws-titlebar-dot ws-titlebar-dot-red" />
          <span className="ws-titlebar-dot ws-titlebar-dot-amber" />
          <span className="ws-titlebar-dot ws-titlebar-dot-green" />
        </div>
        <span className="ws-titlebar-text">SPEED — appwrite/appwrite #11480</span>
      </div>
      <PhaseBar />
      <div className="ws-body">
        <Sidebar
          tree={tree}
          collapsedFolders={collapsedFolders}
          activeFilePath={displayFile?.path ?? null}
          onToggleFolder={onToggleFolder}
          onSelectFile={onSelectFile}
        />
        <div className="ws-main">
          <Editor file={displayFile} visibleFiles={visibleFiles} onSelectFile={onSelectFile} />
          <Terminal />
        </div>
      </div>
    </div>
  );
}

/* ── Joyride ──────────────────────────────────── */

function clamp(v: number, lo: number, hi: number) { return Math.max(lo, Math.min(hi, v)); }

function tipPos(rect: DOMRect, p: Placement): React.CSSProperties {
  const gap = 12;
  const w = p === 'right' ? 260 : 300;
  const tipH = 130;
  const edge = 12;
  const vh = window.innerHeight;
  const vw = window.innerWidth;

  let top: number;
  let left: number;

  if (p === 'right') {
    top = rect.top + 12;
    left = rect.right + gap;
  } else if (p === 'top') {
    top = rect.top - tipH - gap;
    left = rect.left + rect.width / 2 - w / 2;
  } else {
    top = rect.bottom + gap;
    left = rect.left + rect.width / 2 - w / 2;
  }

  return {
    top: clamp(top, edge, vh - tipH - edge),
    left: clamp(left, edge, vw - w - edge),
    maxWidth: w,
  };
}

interface JoyrideProps {
  step: number;
  onNext: () => void;
  onDismiss: () => void;
}

function Joyride({ step, onNext, onDismiss }: JoyrideProps) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const isLast = step === TOUR.length - 1;

  // Scroll workspace into view when tour starts
  useEffect(() => {
    document.querySelector('.ws')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  useEffect(() => {
    const el = document.querySelector(TOUR[step].target);
    if (!el) return;
    const measure = () => setRect(el.getBoundingClientRect());
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [step]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDismiss();
      if (e.key === 'Enter' || e.key === 'ArrowRight') { isLast ? onDismiss() : onNext(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onNext, onDismiss, isLast]);

  if (!rect) return null;

  const pad = 8;
  const spotStyle: React.CSSProperties = {
    top: rect.top - pad,
    left: rect.left - pad,
    width: rect.width + pad * 2,
    height: rect.height + pad * 2,
  };

  return (
    <>
      <div className="jr-overlay" onClick={onDismiss} />
      <div className="jr-spot" style={spotStyle} />
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          className="jr-tip"
          style={tipPos(rect, TOUR[step].placement)}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18 }}
        >
          <p className="jr-title">{TOUR[step].title}</p>
          <p className="jr-body">{TOUR[step].body}</p>
          <div className="jr-footer">
            <div className="jr-dots">
              {TOUR.map((_, i) => (
                <span key={i} className={`jr-dot ${i === step ? 'jr-dot-active' : ''}`} />
              ))}
            </div>
            <div className="jr-actions">
              <button className="jr-skip" onClick={onDismiss}>Skip</button>
              <button className="jr-next" onClick={isLast ? onDismiss : onNext}>
                {isLast ? 'Got it' : 'Next'}
              </button>
            </div>
          </div>
        </motion.div>
      </AnimatePresence>
    </>
  );
}

/* ── Phase Action Bar ─────────────────────────── */

function PhaseBar() {
  const currentStep = useStore($currentStep);
  const ranges      = useStore($phaseRanges);

  return (
    <div className="ws-phases">
      {PHASES.map((p) => {
        const range = ranges.find(r => r.phase === p);
        if (!range) return null;

        const isDone    = currentStep > range.end;
        const isCurrent = currentStep >= range.start && currentStep <= range.end;
        const cls = isDone ? 'ws-phase-done' : isCurrent ? 'ws-phase-current' : 'ws-phase-pending';

        const phaseLen = range.end - range.start;
        const phasePct = isCurrent && phaseLen > 0
          ? ((currentStep - range.start) / phaseLen) * 100
          : isDone ? 100 : 0;

        return (
          <motion.button
            key={p}
            className={`ws-phase ${cls}`}
            onClick={() => playPhase(p)}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
          >
            <span className="ws-phase-indicator">
              {isDone ? (
                <svg width="12" height="12" viewBox="0 0 12 12">
                  <path d="M2.5 6l2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              ) : isCurrent ? (
                <span className="ws-phase-dot ws-phase-dot-active" />
              ) : (
                <span className="ws-phase-dot" />
              )}
            </span>
            <span className="ws-phase-label">
              {isCurrent ? PHASE_META[p].action : PHASE_META[p].label}
            </span>
            {(isCurrent || isDone) && (
              <motion.span
                className="ws-phase-progress"
                initial={{ width: 0 }}
                animate={{ width: `${phasePct}%` }}
                transition={{ duration: 0.1, ease: 'linear' }}
              />
            )}
          </motion.button>
        );
      })}
    </div>
  );
}

/* ── Sidebar ──────────────────────────────────── */

interface SidebarProps {
  tree: TreeNode[];
  collapsedFolders: Set<string>;
  activeFilePath: string | null;
  onToggleFolder: (path: string) => void;
  onSelectFile: (file: FileContent) => void;
}

function Sidebar({ tree, collapsedFolders, activeFilePath, onToggleFolder, onSelectFile }: SidebarProps) {
  return (
    <div className="ws-sidebar">
      <div className="ws-sidebar-chrome">
        <span className="ws-sidebar-title">EXPLORER</span>
      </div>
      <div className="ws-sidebar-body">
        {tree.length === 0 ? (
          <div className="ws-sidebar-empty">No files yet</div>
        ) : (
          tree.map(node => (
            <FileTreeItem
              key={node.fullPath}
              node={node}
              depth={0}
              collapsedFolders={collapsedFolders}
              activeFilePath={activeFilePath}
              onToggleFolder={onToggleFolder}
              onSelectFile={onSelectFile}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface FileTreeItemProps {
  node: TreeNode;
  depth: number;
  collapsedFolders: Set<string>;
  activeFilePath: string | null;
  onToggleFolder: (path: string) => void;
  onSelectFile: (file: FileContent) => void;
}

function FileTreeItem({ node, depth, collapsedFolders, activeFilePath, onToggleFolder, onSelectFile }: FileTreeItemProps) {
  const pad = 12 + depth * 16;

  if (node.type === 'file') {
    const isActive = node.file?.path === activeFilePath;
    return (
      <motion.div
        className={`ws-tree-item ws-tree-file ${isActive ? 'ws-tree-active' : ''}`}
        style={{ paddingLeft: pad }}
        onClick={() => node.file && onSelectFile(node.file)}
        initial={{ opacity: 0, x: -6 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.2 }}
      >
        <span className={`ws-tree-dot ${dotClass(node.name)}`} />
        <span className="ws-tree-name">{node.name}</span>
      </motion.div>
    );
  }

  const expanded = !collapsedFolders.has(node.fullPath);

  return (
    <motion.div
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2 }}
    >
      <div
        className="ws-tree-item ws-tree-folder"
        style={{ paddingLeft: pad }}
        onClick={() => onToggleFolder(node.fullPath)}
      >
        <svg
          className={`ws-tree-chevron ${expanded ? 'ws-tree-chevron-open' : ''}`}
          width="10" height="10" viewBox="0 0 10 10" fill="currentColor"
        >
          <path d="M3 2l4 3-4 3z" />
        </svg>
        <span className="ws-tree-name">{node.name}</span>
      </div>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="children"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            style={{ overflow: 'hidden' }}
          >
            {node.children.map(child => (
              <FileTreeItem
                key={child.fullPath}
                node={child}
                depth={depth + 1}
                collapsedFolders={collapsedFolders}
                activeFilePath={activeFilePath}
                onToggleFolder={onToggleFolder}
                onSelectFile={onSelectFile}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/* ── Editor ───────────────────────────────────── */

interface EditorProps {
  file: FileContent | null;
  visibleFiles: FileContent[];
  onSelectFile: (file: FileContent) => void;
}

function Editor({ file, visibleFiles, onSelectFile }: EditorProps) {
  const isAnnotation = file != null && file.lines[0]?.startsWith('// Review finding');

  return (
    <div className="ws-editor">
      {/* Tab bar */}
      <div className="ws-editor-tabs">
        {visibleFiles.length === 0 ? (
          <span className="ws-tab ws-tab-empty">No files open</span>
        ) : (
          visibleFiles.map((f) => {
            const name = f.path.split('/').pop() ?? f.path;
            const isActive = f.path === file?.path;
            return (
              <button
                key={f.path}
                className={`ws-tab ${isActive ? 'ws-tab-active' : ''}`}
                onClick={() => onSelectFile(f)}
                title={f.path}
              >
                <span className={`ws-tab-dot ${dotClass(name)}`} />
                {name}
              </button>
            );
          })
        )}
        {file && <span className="ws-editor-path">{file.path}</span>}
      </div>

      {/* Code body */}
      <div className="ws-editor-body">
        {!file ? (
          <div className="ws-editor-empty">
            <svg className="ws-editor-empty-icon" width="40" height="40" viewBox="0 0 40 40" fill="none">
              <rect x="7" y="5" width="26" height="30" rx="3" stroke="currentColor" strokeWidth="1.2" />
              <line x1="13" y1="14" x2="27" y2="14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <line x1="13" y1="19" x2="24" y2="19" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <line x1="13" y1="24" x2="20" y2="24" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            <p className="ws-editor-empty-text">Click an action above to begin</p>
          </div>
        ) : isAnnotation ? (
          <AnimatePresence mode="wait">
            <motion.div
              key={file.path + '-' + file.lines[3]}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              <ReviewAnnotation file={file} />
            </motion.div>
          </AnimatePresence>
        ) : file.language === 'markdown' ? (
          <AnimatePresence mode="wait">
            <motion.div
              key={file.path}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <MarkdownPreview lines={file.lines} highlightLines={file.highlightLines} />
            </motion.div>
          </AnimatePresence>
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={file.path}
              className="ws-editor-code"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              {file.lines.map((line, i) => {
                const lineNum = i + 1;
                const isHL = file.highlightLines?.includes(i);
                return (
                  <div key={i} className={`ws-editor-line ${isHL ? 'ws-editor-line-hl' : ''}`}>
                    <span className="ws-editor-linenum">{lineNum}</span>
                    <span className="ws-editor-linetext">{line || '\u00A0'}</span>
                  </div>
                );
              })}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

/* ── Review Annotation ────────────────────────── */

function ReviewAnnotation({ file }: { file: FileContent }) {
  const lineMatch = file.lines[0]?.match(/line (\d+)/);
  const lineNum   = lineMatch ? lineMatch[1] : '?';
  const sevMatch  = file.lines[1]?.match(/\[(.*?)\]/);
  const severity  = sevMatch ? sevMatch[1].toLowerCase() : 'note';
  const message   = file.lines[3] ?? '';
  const sugLine   = file.lines.find(l => l.startsWith('// Suggestion:'));
  const suggestion = sugLine?.replace('// Suggestion: ', '') ?? null;
  const fileName  = file.path.split('/').pop() ?? file.path;

  const sevCls = severity === 'major' ? 'ws-annot-major'
               : severity === 'minor' ? 'ws-annot-minor'
               : 'ws-annot-nit';

  return (
    <div className="ws-annotation-wrap">
      <div className={`ws-annotation ${sevCls}`}>
        <div className="ws-annot-header">
          <span className={`ws-annot-badge ${sevCls}`}>{severity.toUpperCase()}</span>
          <span className="ws-annot-location">{fileName}:{lineNum}</span>
        </div>
        <p className="ws-annot-message">{message}</p>
        {suggestion && (
          <div className="ws-annot-suggestion">
            <span className="ws-annot-suggestion-label">Suggestion</span>
            <p className="ws-annot-suggestion-text">{suggestion}</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Markdown Preview ──────────────────────────── */

function mdInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let rest = text;
  let k = 0;
  while (rest.length > 0) {
    const bold = rest.match(/\*\*(.*?)\*\*/);
    const code = rest.match(/`(.*?)`/);
    const bIdx = bold ? rest.indexOf(bold[0]) : Infinity;
    const cIdx = code ? rest.indexOf(code[0]) : Infinity;
    if (bIdx === Infinity && cIdx === Infinity) { parts.push(rest); break; }
    const idx = Math.min(bIdx, cIdx);
    if (idx > 0) parts.push(rest.slice(0, idx));
    if (bIdx < cIdx && bold) {
      parts.push(<strong key={k++}>{bold[1]}</strong>);
      rest = rest.slice(idx + bold[0].length);
    } else if (code) {
      parts.push(<code key={k++} className="md-ic">{code[1]}</code>);
      rest = rest.slice(idx + code[0].length);
    }
  }
  return parts.length === 1 && typeof parts[0] === 'string' ? parts[0] : <>{parts}</>;
}

function MarkdownPreview({ lines, highlightLines }: { lines: string[]; highlightLines?: number[] }) {
  const els: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const hl = highlightLines?.includes(i) ? ' md-hl' : '';

    // Code block
    if (line.startsWith('```')) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++;
      els.push(<pre key={i} className="md-codeblock"><code>{codeLines.join('\n')}</code></pre>);
      continue;
    }
    // Headings
    if (line.startsWith('# '))   { els.push(<h2 key={i} className={`md-h1${hl}`}>{mdInline(line.slice(2))}</h2>); i++; continue; }
    if (line.startsWith('## '))  { els.push(<h3 key={i} className={`md-h2${hl}`}>{mdInline(line.slice(3))}</h3>); i++; continue; }
    if (line.startsWith('### ')) { els.push(<h4 key={i} className={`md-h3${hl}`}>{mdInline(line.slice(4))}</h4>); i++; continue; }
    // Blockquote
    if (line.startsWith('> '))   { els.push(<blockquote key={i} className={`md-bq${hl}`}>{mdInline(line.slice(2))}</blockquote>); i++; continue; }
    // Table: collect all | rows
    if (line.startsWith('|')) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].startsWith('|')) { rows.push(lines[i]); i++; }
      const dataRows = rows.filter(r => !r.match(/^\|[\s-|]+\|$/));
      els.push(
        <table key={i} className="md-table">
          <tbody>
            {dataRows.map((r, ri) => (
              <tr key={ri} className={ri === 0 ? 'md-thead' : ''}>
                {r.split('|').filter(Boolean).map((cell, ci) => (
                  <td key={ci}>{mdInline(cell.trim())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
      continue;
    }
    // Checkbox
    if (line.match(/^-\s\[[ x]\]\s/)) {
      const checked = line.includes('[x]');
      els.push(
        <div key={i} className={`md-check${hl}`}>
          <span className={checked ? 'md-check-on' : 'md-check-off'}>{checked ? '✓' : '○'}</span>
          <span>{mdInline(line.replace(/^-\s\[[ x]\]\s/, ''))}</span>
        </div>
      );
      i++; continue;
    }
    // List item (including nested)
    if (line.trimStart().startsWith('- ')) {
      const indent = line.length - line.trimStart().length;
      els.push(
        <div key={i} className={`md-li${hl}`} style={indent > 0 ? { paddingLeft: indent * 4 } : undefined}>
          <span className="md-bullet">•</span>
          <span>{mdInline(line.trimStart().slice(2))}</span>
        </div>
      );
      i++; continue;
    }
    // Branch indicators
    if (line.trimStart().startsWith('←') || line.trimStart().startsWith('→')) {
      const isTarget = line.trimStart().startsWith('→');
      els.push(
        <div key={i} className={`md-branch${isTarget ? ' md-branch-target' : ''}${hl}`}>
          {line.trim()}
        </div>
      );
      i++; continue;
    }
    // Empty line
    if (line.trim() === '') { els.push(<div key={i} className="md-spacer" />); i++; continue; }
    // Paragraph
    els.push(<p key={i} className={`md-p${hl}`}>{mdInline(line)}</p>);
    i++;
  }

  return <div className="md-preview">{els}</div>;
}

/* ── Terminal ─────────────────────────────────── */

function Terminal() {
  const visibleSteps = useStore($visibleSteps);
  const phase = useStore($phase);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [visibleSteps.length]);

  // Only show terminal lines from the current phase
  const allLines = useMemo(() => {
    const lines: { line: TerminalLine; key: string; isNew: boolean }[] = [];
    for (let s = 0; s < visibleSteps.length; s++) {
      const step = visibleSteps[s];
      if (step.phase !== phase) continue;
      for (let l = 0; l < step.terminal.length; l++) {
        lines.push({
          line: step.terminal[l],
          key: `${step.id}-${l}`,
          isNew: s === visibleSteps.length - 1,
        });
      }
    }
    return lines;
  }, [visibleSteps, phase]);

  return (
    <div className="ws-terminal">
      <div className="ws-terminal-chrome">
        <span className="ws-terminal-title">TERMINAL</span>
        <span className="ws-terminal-phase">{phase}</span>
      </div>
      <div className="ws-terminal-body">
        {allLines.map((entry) => {
          const cls = `ws-tline ws-tline-${entry.line.color}`;
          const style = entry.line.indent
            ? { paddingLeft: `${entry.line.indent * 12}px` }
            : undefined;

          if (entry.isNew) {
            return (
              <motion.div
                key={entry.key}
                className={cls}
                style={style}
                initial={{ opacity: 0, y: 3 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.12 }}
              >
                {entry.line.text || '\u00A0'}
                {entry.line.color === 'green' && entry.line.text.includes('\u2713') && (
                  <motion.span
                    className="ws-tline-flash ws-tline-flash-green"
                    initial={{ opacity: 0.25 }}
                    animate={{ opacity: 0 }}
                    transition={{ duration: 0.8 }}
                  />
                )}
                {entry.line.color === 'amber' && (
                  <motion.span
                    className="ws-tline-flash ws-tline-flash-amber"
                    initial={{ opacity: 0.2 }}
                    animate={{ opacity: 0 }}
                    transition={{ duration: 0.8 }}
                  />
                )}
              </motion.div>
            );
          }

          return (
            <div key={entry.key} className={cls} style={style}>
              {entry.line.text || '\u00A0'}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

