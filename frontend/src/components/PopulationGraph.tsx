import { useEffect, useState } from 'react';
import { useWorldStore } from '../store/worldStore';

const HISTORY_SIZE = 80;
const GRAPH_WIDTH = 200;
const GRAPH_HEIGHT = 50;
const LINE_COLOR = '#4dff91';
const FILL_COLOR = 'rgba(77,255,145,0.12)';

interface SparklineProps {
  readonly values: readonly number[];
  readonly width: number;
  readonly height: number;
}

function Sparkline({ values, width, height }: SparklineProps): React.JSX.Element {
  if (values.length < 2) {
    return (
      <svg width={width} height={height}>
        <line x1={0} y1={height / 2} x2={width} y2={height / 2} stroke={LINE_COLOR} strokeWidth={1} strokeOpacity={0.3} />
      </svg>
    );
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const toY = (v: number): number =>
    height - ((v - min) / range) * (height - 4) - 2;

  const stepX = width / (values.length - 1);

  const points = values.map((v, i) => `${i * stepX},${toY(v)}`).join(' ');
  const fillPoints = `0,${height} ${points} ${(values.length - 1) * stepX},${height}`;

  return (
    <svg width={width} height={height} style={{ overflow: 'visible' }}>
      <polygon points={fillPoints} fill={FILL_COLOR} />
      <polyline points={points} fill="none" stroke={LINE_COLOR} strokeWidth={1.5} strokeLinejoin="round" />
      {/* Current value dot */}
      <circle
        cx={(values.length - 1) * stepX}
        cy={toY(values[values.length - 1]!)}
        r={2.5}
        fill={LINE_COLOR}
      />
    </svg>
  );
}

/**
 * PopulationGraph — real-time SVG sparkline of entity count.
 *
 * Keeps last HISTORY_SIZE samples, renders in bottom-right corner.
 */
export function PopulationGraph(): React.JSX.Element {
  const entityCount = useWorldStore((s) => s.entityCount);
  const [history, setHistory] = useState<readonly number[]>([]);

  useEffect(() => {
    setHistory((prev) => {
      const next = [...prev, entityCount];
      return next.length > HISTORY_SIZE ? next.slice(next.length - HISTORY_SIZE) : next;
    });
  }, [entityCount]);

  const current = history[history.length - 1] ?? entityCount;

  return (
    <div className="population-graph">
      <div className="population-graph__header-row">
        <span className="population-graph__label">Population</span>
        <span className="population-graph__count">{current}</span>
      </div>
      <Sparkline values={history} width={GRAPH_WIDTH} height={GRAPH_HEIGHT} />
    </div>
  );
}
