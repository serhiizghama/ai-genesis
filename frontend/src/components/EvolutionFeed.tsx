import { useEffect, useRef } from 'react';
import { Eye, Brain, Code2, Wand2 } from 'lucide-react';
import { useWorldStore } from '../store/worldStore';
import type { FeedMessage } from '../store/worldStore';

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

function formatTime(timestamp: number): string {
  const d = new Date(timestamp * 1000);
  return d.toLocaleTimeString('en-US', { hour12: false });
}

interface FeedItemProps {
  readonly msg: FeedMessage;
}

function FeedItem({ msg }: FeedItemProps): React.JSX.Element {
  const style = AGENT_STYLES[msg.agent] ?? DEFAULT_STYLE;
  const { Icon, color, bg, label } = style;

  return (
    <div
      style={{
        display: 'flex',
        gap: '8px',
        alignItems: 'flex-start',
        padding: '6px 10px',
        background: bg,
        borderLeft: `2px solid ${color}`,
        borderRadius: '2px',
        marginBottom: '4px',
      }}
    >
      <Icon size={14} color={color} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '2px' }}>
          <span style={{ fontSize: '10px', fontWeight: 700, color, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            {label}
          </span>
          <span style={{ fontSize: '9px', color: 'rgba(255,255,255,0.35)' }}>
            {formatTime(msg.timestamp)}
          </span>
        </div>
        <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.85)', wordBreak: 'break-word', lineHeight: 1.4 }}>
          {msg.text}
        </span>
      </div>
    </div>
  );
}

/**
 * EvolutionFeed — semi-transparent overlay showing real-time agent messages.
 *
 * Positioned on the right side of the screen.
 * Color-coded by agent: Watcher=red, Architect=blue, Coder=green, Patcher=purple.
 * Auto-scrolls to the latest message.
 */
export function EvolutionFeed(): React.JSX.Element {
  const feedMessages = useWorldStore((s) => s.feedMessages);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [feedMessages]);

  return (
    <div
      style={{
        position: 'fixed',
        top: '16px',
        right: '16px',
        width: '280px',
        maxHeight: 'calc(100vh - 160px)',
        display: 'flex',
        flexDirection: 'column',
        background: 'rgba(10, 10, 20, 0.75)',
        backdropFilter: 'blur(8px)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '6px',
        overflow: 'hidden',
        fontFamily: 'monospace',
        zIndex: 100,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '8px 10px',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          fontSize: '10px',
          fontWeight: 700,
          color: 'rgba(255,255,255,0.5)',
          textTransform: 'uppercase',
          letterSpacing: '1px',
          flexShrink: 0,
        }}
      >
        Evolution Feed
      </div>

      {/* Messages */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '6px',
          scrollbarWidth: 'thin',
          scrollbarColor: 'rgba(255,255,255,0.15) transparent',
        }}
      >
        {feedMessages.length === 0 ? (
          <div style={{ padding: '12px 8px', fontSize: '10px', color: 'rgba(255,255,255,0.25)', textAlign: 'center' }}>
            Waiting for agent activity…
          </div>
        ) : (
          feedMessages.map((msg) => <FeedItem key={msg.id} msg={msg} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
