import { useEffect, useRef } from 'react';
import { useWorldStream, type EntityState } from '../hooks/useWorldStream';

/**
 * Debug canvas component that renders entities as colored circles.
 *
 * Uses HTML Canvas 2D API (not PixiJS) for simple debugging.
 * Renders in real-time using requestAnimationFrame.
 */
export function DebugCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { entities, tick, connected } = useWorldStream();
  const animationFrameRef = useRef<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Set canvas size to match window
    const resizeCanvas = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    // Render loop using requestAnimationFrame
    const render = () => {
      // Clear canvas
      ctx.fillStyle = '#0a0a0f'; // Dark background
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Draw entities
      entities.forEach((entity: EntityState) => {
        drawEntity(ctx, entity);
      });

      // Draw connection status
      drawStatus(ctx, connected, tick, entities.length);

      // Continue loop
      animationFrameRef.current = requestAnimationFrame(render);
    };

    // Start render loop
    render();

    // Cleanup
    return () => {
      window.removeEventListener('resize', resizeCanvas);
      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [entities, tick, connected]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        display: 'block',
        width: '100%',
        height: '100%',
        margin: 0,
        padding: 0,
      }}
    />
  );
}

/**
 * Draw a single entity as a colored circle.
 *
 * @param ctx - Canvas rendering context
 * @param entity - Entity to draw
 */
function drawEntity(ctx: CanvasRenderingContext2D, entity: EntityState): void {
  ctx.beginPath();
  ctx.arc(entity.x, entity.y, entity.radius, 0, Math.PI * 2);
  ctx.fillStyle = entity.color;
  ctx.fill();
  ctx.closePath();
}

/**
 * Draw status information in the top-left corner.
 *
 * @param ctx - Canvas rendering context
 * @param connected - WebSocket connection status
 * @param tick - Current simulation tick
 * @param entityCount - Number of entities
 */
function drawStatus(
  ctx: CanvasRenderingContext2D,
  connected: boolean,
  tick: number,
  entityCount: number
): void {
  ctx.fillStyle = connected ? '#00ff00' : '#ff0000';
  ctx.font = '14px monospace';

  const status = connected ? 'CONNECTED' : 'DISCONNECTED';
  ctx.fillText(`${status} | Tick: ${tick} | Entities: ${entityCount}`, 10, 20);
}
