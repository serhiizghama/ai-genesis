import { useEffect, useRef } from 'react';
import { Eye, Brain, Code2, Wand2 } from 'lucide-react';
import { useWorldStore } from '../store/worldStore';
import type { FeedMessage } from '../types/feed';

interface AgentStyle {
  readonly color: string;
  readonly bg: string;
  readonly label: string;
  readonly Icon: React.ComponentType<{ size?: number; color?: string }>;
}

const AGENT_STYLES: Record<string, AgentStyle> = {
  watcher: {
    color: '#ff4d4d',
    bg: 'rgba(255, 77, 77, 0.12)',
    label: 'Watcher',
    Icon: Eye,
  },
  architect: {
    color: '#4d9fff',
    bg: 'rgba(77, 159, 255, 0.12)',
    label: 'Architect',
    Icon: Brain,
  },
  coder: {
    color: '#4dff91',
    bg: 'rgba(77, 255, 145, 0.12)',
    label: 'Coder',
    Icon: Code2,
  },
  patcher: {
    color: '#c084fc',
    bg: 'rgba(192, 132, 252, 0.12)',
    label: 'Patcher',
    Icon: Wand2,
  },
} as const;

const DEFAULT_STYLE: AgentStyle = {
  color: '#aaaaaa',
  bg: 'rgba(170, 170, 170, 0.08)',
  label: 'System',
  Icon: Eye,
};

const SEVERITY_CHIP_COLOR: Record<string, string> = {
  low: '#4dff91',
  medium: '#f59e0b',
  high: '#ff9544',
  critical: '#ff4d4d',
};

function formatTime(timestamp: number): string {
  const d = new Date(timestamp * 1000);
  return d.toLocaleTimeString('en-US', { hour12: false });
}

interface FeedItemProps {
  readonly msg: FeedMessage;
  readonly isSelected: boolean;
  readonly onClick: (msg: FeedMessage) => void;
}

function FeedItem({ msg, isSelected, onClick }: FeedItemProps): React.JSX.Element {
  const style = AGENT_STYLES[msg.agent] ?? DEFAULT_STYLE;
  const { Icon, color, bg, label } = style;
  const trigger = msg.metadata?.trigger;
  const mutation = msg.metadata?.mutation;

  return (
    <div
      onClick={() => onClick(msg)}
      style={{
        display: 'flex',
        gap: '8px',
        alignItems: 'flex-start',
        padding: '6px 10px',
        background: isSelected ? `${bg.replace('0.12', '0.22')}` : bg,
        borderLeft: `2px solid ${isSelected ? color : `${color}88`}`,
        borderRadius: '2px',
        marginBottom: '4px',
        cursor: 'pointer',
        transition: 'background 0.15s, border-color 0.15s',
        outline: isSelected ? `1px solid ${color}44` : 'none',
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onClick(msg); }}
    >
      <Icon size={14} color={color} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '2px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '10px', fontWeight: 700, color, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            {label}
          </span>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.35)' }}>
            {formatTime(msg.timestamp)}
          </span>
          {trigger && (
            <span
              style={{
                display: 'inline-block',
                padding: '0px 4px',
                borderRadius: '2px',
                fontSize: '8px',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.3px',
                color: SEVERITY_CHIP_COLOR[trigger.severity] ?? '#aaaaaa',
                border: `1px solid ${SEVERITY_CHIP_COLOR[trigger.severity] ?? '#aaaaaa'}`,
                background: `${SEVERITY_CHIP_COLOR[trigger.severity] ?? '#aaaaaa'}18`,
              }}
            >
              {trigger.problem_type} · {trigger.severity}
            </span>
          )}
          {mutation && !trigger && (
            <span
              style={{
                display: 'inline-block',
                padding: '0px 4px',
                borderRadius: '2px',
                fontSize: '8px',
                fontWeight: 600,
                color: '#c084fc',
                border: '1px solid rgba(192,132,252,0.4)',
                background: 'rgba(192,132,252,0.1)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {mutation.trait_name} v{mutation.version}
            </span>
          )}
        </div>
        <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.85)', wordBreak: 'break-word', lineHeight: 1.4 }}>
          {msg.message}
        </span>
      </div>
    </div>
  );
}

interface CycleDividerProps {
  readonly cycleId: string;
}

function CycleDivider({ cycleId }: CycleDividerProps): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        margin: '8px 0 4px',
        padding: '0 2px',
      }}
    >
      <div style={{ flex: 1, height: '1px', background: 'var(--border)' }} />
      <span style={{ fontSize: '8px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', letterSpacing: '0.5px' }}>
        {cycleId}
      </span>
      <div style={{ flex: 1, height: '1px', background: 'var(--border)' }} />
    </div>
  );
}

interface EvolutionFeedProps {
  readonly selectedId: number | null;
  readonly onSelect: (msg: FeedMessage | null) => void;
}

/**
 * EvolutionFeed — semi-transparent overlay showing real-time agent messages.
 *
 * Positioned on the right side of the screen.
 * Color-coded by agent: Watcher=red, Architect=blue, Coder=green, Patcher=purple.
 * Auto-scrolls to the latest message.
 * Click a message to open DeveloperPanel.
 */
export function EvolutionFeed({ selectedId, onSelect }: EvolutionFeedProps): React.JSX.Element {
  const feedMessages = useWorldStore((s) => s.feedMessages);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [feedMessages]);

  const handleClick = (msg: FeedMessage): void => {
    onSelect(selectedId === msg.id ? null : msg);
  };

  // Group messages by cycle_id, track the last seen cycle_id to show dividers
  const rendered: React.ReactNode[] = [];
  let lastCycleId: string | undefined;

  feedMessages.forEach((msg) => {
    const cycleId = msg.metadata?.cycle_id;
    if (cycleId && cycleId !== lastCycleId) {
      rendered.push(<CycleDivider key={`div-${cycleId}`} cycleId={cycleId} />);
      lastCycleId = cycleId;
    }
    rendered.push(
      <FeedItem
        key={msg.id}
        msg={msg}
        isSelected={selectedId === msg.id}
        onClick={handleClick}
      />
    );
  });

  return (
    <div className="evolution-feed">
      <div className="evolution-feed__header-row">Evolution Feed</div>
      <div className="evolution-feed__scroll">
        {feedMessages.length === 0 ? (
          <div style={{ padding: '12px 8px', fontSize: '10px', color: 'rgba(255,255,255,0.25)', textAlign: 'center' }}>
            Waiting for agent activity…
          </div>
        ) : (
          rendered
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
