import { useState, useEffect } from 'react';
import { X, ChevronDown, ChevronRight, Code2, FileCode } from 'lucide-react';
import type { FeedMessage, FeedTriggerMeta, FeedPlanMeta } from '../types/feed';

interface DeveloperPanelProps {
  readonly msg: FeedMessage;
  readonly onClose: () => void;
}

const SEVERITY_COLOR: Record<string, string> = {
  low: '#4dff91',
  medium: '#f59e0b',
  high: '#ff9544',
  critical: '#ff4d4d',
};

function SeverityBadge({ severity }: { readonly severity: string }): React.JSX.Element {
  const color = SEVERITY_COLOR[severity] ?? '#aaaaaa';
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 6px',
        borderRadius: '3px',
        fontSize: '9px',
        fontWeight: 700,
        letterSpacing: '0.5px',
        textTransform: 'uppercase',
        color,
        border: `1px solid ${color}`,
        background: `${color}22`,
      }}
    >
      {severity}
    </span>
  );
}

function TriggerSection({ trigger }: { readonly trigger: FeedTriggerMeta }): React.JSX.Element {
  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ fontSize: '9px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '6px' }}>
        Trigger
      </div>
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '6px' }}>
        <span style={{ fontSize: '11px', color: 'var(--text-primary)', fontWeight: 600 }}>{trigger.problem_type}</span>
        <SeverityBadge severity={trigger.severity} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px' }}>
        {trigger.entity_count !== undefined && (
          <MetricRow label="Entities" value={String(trigger.entity_count)} />
        )}
        {trigger.avg_energy !== undefined && (
          <MetricRow label="Avg energy" value={trigger.avg_energy.toFixed(1)} />
        )}
        {trigger.snapshot_tick !== undefined && (
          <MetricRow label="Tick" value={String(trigger.snapshot_tick)} />
        )}
        {trigger.dominant_trait && (
          <MetricRow label="Dom. trait" value={trigger.dominant_trait} />
        )}
      </div>
    </div>
  );
}

function MetricRow({ label, value }: { readonly label: string; readonly value: string }): React.JSX.Element {
  return (
    <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '3px', padding: '4px 6px' }}>
      <div style={{ fontSize: '8px', color: 'var(--text-secondary)', marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
      <div style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</div>
    </div>
  );
}

function PlanSection({ plan }: { readonly plan: FeedPlanMeta }): React.JSX.Element {
  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ fontSize: '9px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '6px' }}>
        Plan
      </div>
      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginBottom: '6px' }}>
        <Tag text={plan.change_type} color="var(--accent-blue)" />
        {plan.target_class && <Tag text={plan.target_class} color="var(--accent-purple)" />}
        {plan.target_method && <Tag text={`.${plan.target_method}()`} color="var(--accent-purple)" />}
      </div>
      <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.8)', lineHeight: 1.5, marginBottom: '6px' }}>
        {plan.description}
      </p>
      {plan.expected_outcome && (
        <div style={{ fontSize: '10px', color: 'var(--accent-green)', marginBottom: '6px', fontStyle: 'italic' }}>
          → {plan.expected_outcome}
        </div>
      )}
      {plan.constraints && plan.constraints.length > 0 && (
        <div>
          <div style={{ fontSize: '9px', color: 'var(--text-secondary)', marginBottom: '3px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Constraints</div>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {plan.constraints.map((c, i) => (
              <li key={i} style={{ fontSize: '10px', color: 'rgba(255,255,255,0.6)', paddingLeft: '8px', borderLeft: '2px solid var(--accent-amber)' }}>
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Tag({ text, color }: { readonly text: string; readonly color: string }): React.JSX.Element {
  return (
    <span style={{ display: 'inline-block', padding: '1px 6px', borderRadius: '3px', fontSize: '9px', fontWeight: 600, fontFamily: 'var(--font-mono)', color, border: `1px solid ${color}40`, background: `${color}15` }}>
      {text}
    </span>
  );
}

interface FullCodeViewerProps {
  readonly mutationId: string;
  readonly onClose: () => void;
}

function FullCodeViewer({ mutationId, onClose }: FullCodeViewerProps): React.JSX.Element {
  const [code, setCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/mutations/${mutationId}/source`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ source_code: string; trait_name: string }>;
      })
      .then((data) => {
        setCode(data.source_code);
        setLoading(false);
      })
      .catch((err: Error) => {
        setError(err.message);
        setLoading(false);
      });
  }, [mutationId]);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.75)',
        zIndex: 200,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--bg-panel)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          width: '640px',
          maxHeight: '80vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px' }}>
            <FileCode size={12} />
            Full source
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '16px', lineHeight: 1, padding: 0 }}
          >
            ×
          </button>
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: '12px 14px' }}>
          {loading && <div style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>Loading…</div>}
          {error && <div style={{ color: 'var(--accent-red)', fontSize: '12px' }}>Error: {error}</div>}
          {code && (
            <pre style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.85)', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0 }}>
              {code}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

function CodeSection({ msg }: { readonly msg: FeedMessage }): React.JSX.Element | null {
  const [showFull, setShowFull] = useState(false);
  const { metadata } = msg;
  if (!metadata) return null;

  const { code, mutation } = metadata;
  const hasSnippet = code?.snippet;
  const hasErrors = code?.validation_errors;
  const hasMutation = !!mutation;

  if (!hasSnippet && !hasErrors && !hasMutation) return null;

  return (
    <div>
      <div style={{ fontSize: '9px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '4px' }}>
        <Code2 size={10} />
        Code
      </div>
      {mutation && (
        <div style={{ fontSize: '10px', color: 'var(--accent-purple)', fontFamily: 'var(--font-mono)', marginBottom: '6px' }}>
          {mutation.trait_name} v{mutation.version}
          {mutation.file_path && <span style={{ color: 'var(--text-secondary)', marginLeft: '6px' }}>{mutation.file_path}</span>}
        </div>
      )}
      {hasErrors && (
        <div style={{ fontSize: '10px', color: 'var(--accent-red)', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: '3px', padding: '6px 8px', marginBottom: '6px', fontFamily: 'var(--font-mono)' }}>
          {code?.validation_errors}
        </div>
      )}
      {hasSnippet && (
        <pre style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'rgba(255,255,255,0.8)', lineHeight: 1.5, background: 'rgba(0,0,0,0.3)', borderRadius: '3px', padding: '8px', overflow: 'auto', maxHeight: '200px', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {code?.snippet}
        </pre>
      )}
      {mutation && (
        <button
          onClick={() => setShowFull(true)}
          style={{
            marginTop: '6px',
            background: 'rgba(77,159,255,0.08)',
            border: '1px solid rgba(77,159,255,0.25)',
            color: '#4d9fff',
            fontFamily: 'var(--font-mono)',
            fontSize: '10px',
            fontWeight: 600,
            padding: '4px 10px',
            borderRadius: '4px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          <FileCode size={10} />
          View full code
        </button>
      )}
      {showFull && mutation && (
        <FullCodeViewer mutationId={mutation.mutation_id} onClose={() => setShowFull(false)} />
      )}
    </div>
  );
}

function RegistrySection({ msg }: { readonly msg: FeedMessage }): React.JSX.Element | null {
  const registry = msg.metadata?.registry;
  const error = msg.metadata?.error;
  if (!registry && !error) return null;

  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ fontSize: '9px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '6px' }}>
        Registry
      </div>
      {registry?.registry_version !== undefined && (
        <div style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>
          Version: <span style={{ color: 'var(--accent-green)' }}>#{registry.registry_version}</span>
        </div>
      )}
      {registry?.rollback_to && (
        <div style={{ fontSize: '10px', color: 'var(--accent-amber)', marginBottom: '4px' }}>
          Rolled back to: {String(registry.rollback_to)}
        </div>
      )}
      {typeof error === 'string' && (
        <div style={{ fontSize: '10px', color: 'var(--accent-red)', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: '3px', padding: '6px 8px', fontFamily: 'var(--font-mono)' }}>
          {error}
        </div>
      )}
    </div>
  );
}

function CollapseSection({
  title,
  defaultOpen = true,
  children,
}: {
  readonly title: string;
  readonly defaultOpen?: boolean;
  readonly children: React.ReactNode;
}): React.JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: '10px', marginBottom: '10px' }}>
      <button
        onClick={() => setOpen(!open)}
        style={{ display: 'flex', alignItems: 'center', gap: '4px', background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '0 0 6px 0', width: '100%', textAlign: 'left' }}
      >
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        <span style={{ fontSize: '9px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px' }}>{title}</span>
      </button>
      {open && children}
    </div>
  );
}

export function DeveloperPanel({ msg, onClose }: DeveloperPanelProps): React.JSX.Element {
  const { metadata } = msg;

  const hasTrigger = !!metadata?.trigger;
  const hasPlan = !!metadata?.plan;
  const hasMutation = !!metadata?.mutation;
  const hasCode = !!metadata?.code;
  const hasRegistry = !!metadata?.registry || typeof metadata?.error === 'string';

  return (
    <aside
      style={{
        display: 'flex',
        flexDirection: 'column',
        borderLeft: '1px solid var(--border)',
        background: 'var(--bg-panel)',
        overflow: 'hidden',
        minHeight: 0,
        width: '300px',
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 10px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-secondary)',
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ fontSize: '9px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '1px' }}>
            Dev Panel
          </div>
          {metadata?.cycle_id && (
            <div style={{ fontSize: '9px', color: 'var(--accent-blue)', fontFamily: 'var(--font-mono)', marginTop: '1px' }}>
              {metadata.cycle_id}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', lineHeight: 1, padding: '2px' }}
          title="Close"
        >
          <X size={14} />
        </button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px', scrollbarWidth: 'thin', scrollbarColor: 'var(--border) transparent' }}>
        {/* Message summary */}
        <div style={{ marginBottom: '12px', padding: '6px 8px', background: 'rgba(255,255,255,0.03)', borderRadius: '4px', borderLeft: '2px solid var(--border)' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', marginBottom: '3px' }}>
            {msg.agent} / {msg.action || '—'}
          </div>
          <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.85)', lineHeight: 1.4 }}>
            {msg.message}
          </div>
        </div>

        {/* Trigger */}
        {hasTrigger && (
          <CollapseSection title="Summary">
            <TriggerSection trigger={metadata!.trigger!} />
          </CollapseSection>
        )}

        {/* Plan */}
        {hasPlan && (
          <CollapseSection title="Plan">
            <PlanSection plan={metadata!.plan!} />
          </CollapseSection>
        )}

        {/* Code / Mutation */}
        {(hasMutation || hasCode) && (
          <CollapseSection title="Code">
            <CodeSection msg={msg} />
          </CollapseSection>
        )}

        {/* Registry */}
        {hasRegistry && (
          <CollapseSection title="Registry">
            <RegistrySection msg={msg} />
          </CollapseSection>
        )}

        {!hasTrigger && !hasPlan && !hasMutation && !hasCode && !hasRegistry && (
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)', textAlign: 'center', padding: '12px 0' }}>
            No metadata available for this message.
          </div>
        )}
      </div>
    </aside>
  );
}
