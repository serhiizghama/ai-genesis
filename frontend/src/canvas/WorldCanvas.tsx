import { extend } from '@pixi/react';
import { Container } from 'pixi.js';
import { useWorldStream } from '../hooks/useWorldStream';
import { useWorldStore } from '../store/worldStore';
import { MolbotSprite } from './MolbotSprite';
import { ResourceDot } from './ResourceDot';

extend({ Container });

/**
 * WorldCanvas — PixiJS scene that renders entities and resources.
 *
 * Reads world state directly from useWorldStream for low-latency 60 FPS rendering.
 * The store is intentionally bypassed here to avoid extra re-renders.
 */
export function WorldCanvas() {
  const { entities } = useWorldStream();
  const selectEntity = useWorldStore((s) => s.selectEntity);

  return (
    <pixiContainer>
      {entities.map((entity) => (
        <MolbotSprite
          key={entity.id}
          x={entity.x}
          y={entity.y}
          color={parseInt(entity.color.slice(1), 16)}
          energy={Math.min(Math.max((entity.radius / 12) * 100, 0), 100)}
          onClick={() => selectEntity(entity.id)}
        />
      ))}
      {/* ResourceDot stub — rendered at origin until the stream carries resource data */}
      <ResourceDot x={0} y={0} energy={0} />
    </pixiContainer>
  );
}
