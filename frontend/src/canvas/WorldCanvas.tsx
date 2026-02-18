import { extend, useApplication } from '@pixi/react';
import { Container, Graphics, Rectangle } from 'pixi.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorldStream } from '../hooks/useWorldStream';
import { useWorldStore } from '../store/worldStore';
import { MolbotSprite } from './MolbotSprite';
import { PredatorSprite } from './PredatorSprite';
import { ResourceDot } from './ResourceDot';

extend({ Container, Graphics });

const ZOOM_SPEED = 0.001;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 8;

interface Camera {
  x: number;
  y: number;
  scale: number;
}

/**
 * WorldCanvas — PixiJS scene that renders entities and resources.
 *
 * Supports:
 * - Scroll wheel to zoom (centered on cursor)
 * - Left-drag to pan
 *
 * Reads world state directly from useWorldStream for low-latency rendering.
 */
export function WorldCanvas() {
  const { entities, resources } = useWorldStream();
  const selectEntity = useWorldStore((s) => s.selectEntity);
  const { app } = useApplication();

  const [camera, setCamera] = useState<Camera>({ x: 0, y: 0, scale: 1 });

  const isDragging = useRef(false);
  const hasMoved = useRef(false);
  const lastPointer = useRef({ x: 0, y: 0 });

  // Scroll wheel → zoom centered on mouse cursor
  useEffect(() => {
    const canvas = app.canvas;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();

      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      const zoomFactor = 1 - e.deltaY * ZOOM_SPEED;

      setCamera((prev) => {
        const newScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, prev.scale * zoomFactor));
        const ratio = newScale / prev.scale;
        return {
          x: mouseX - (mouseX - prev.x) * ratio,
          y: mouseY - (mouseY - prev.y) * ratio,
          scale: newScale,
        };
      });
    };

    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [app]);

  // Pointer drag → pan; track hasMoved so entity clicks still fire
  useEffect(() => {
    const stage = app.stage;
    stage.eventMode = 'static';
    stage.hitArea = new Rectangle(0, 0, app.screen.width, app.screen.height);

    const onDown = (e: PointerEvent) => {
      isDragging.current = true;
      hasMoved.current = false;
      lastPointer.current = { x: e.clientX, y: e.clientY };
    };

    const onMove = (e: PointerEvent) => {
      if (!isDragging.current) return;
      const dx = e.clientX - lastPointer.current.x;
      const dy = e.clientY - lastPointer.current.y;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) hasMoved.current = true;
      lastPointer.current = { x: e.clientX, y: e.clientY };
      if (hasMoved.current) {
        setCamera((prev) => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
      }
    };

    const onUp = () => { isDragging.current = false; };

    const canvas = app.canvas;
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointerleave', onUp);

    return () => {
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointerleave', onUp);
    };
  }, [app]);

  // Update stage hitArea on resize
  useEffect(() => {
    const onResize = () => {
      app.stage.hitArea = new Rectangle(0, 0, app.screen.width, app.screen.height);
    };
    app.renderer.on('resize', onResize);
    return () => { app.renderer.off('resize', onResize); };
  }, [app]);

  const handleEntityClick = useCallback(
    (id: number) => {
      if (!hasMoved.current) selectEntity(id);
    },
    [selectEntity],
  );

  return (
    <pixiContainer x={camera.x} y={camera.y} scale={camera.scale}>
      {resources.map((resource, i) => (
        <ResourceDot key={i} x={resource.x} y={resource.y} />
      ))}
      {entities.map((entity) =>
        entity.isPredator ? (
          <PredatorSprite
            key={entity.id}
            x={entity.x}
            y={entity.y}
            onClick={() => handleEntityClick(entity.id)}
          />
        ) : (
          <MolbotSprite
            key={entity.id}
            x={entity.x}
            y={entity.y}
            color={parseInt(entity.color.slice(1), 16)}
            energy={Math.min(Math.max((entity.radius / 12) * 100, 0), 100)}
            isInfected={entity.isInfected}
            onClick={() => handleEntityClick(entity.id)}
          />
        )
      )}
    </pixiContainer>
  );
}
