import { extend, useTick } from '@pixi/react'
import { Graphics } from 'pixi.js'
import { useCallback, useLayoutEffect, useRef } from 'react'

extend({ Graphics })

interface MolbotSpriteProps {
  /** World X coordinate (server target) */
  x: number
  /** World Y coordinate (server target) */
  y: number
  /** Fill colour as a 24-bit hex number (e.g. 0xff6633) */
  color: number
  /** Energy level 0–100; controls body radius (4–12 px) */
  energy: number
  /** Whether this entity is infected (renders purple with pulse) */
  isInfected?: boolean
  /** Optional click handler */
  onClick?: () => void
}

/**
 * How fast to interpolate toward the server position each frame.
 * 0.22 at 60fps ≈ 90% of distance covered in ~9 frames (~150ms).
 */
const LERP = 0.22

/**
 * MolbotSprite — PixiJS Graphics sprite for a simulation entity.
 *
 * Positions are client-side interpolated (lerp) each frame toward the
 * latest server-provided target, eliminating the "teleport" effect when
 * world frames arrive at a lower rate than the render loop.
 */
export function MolbotSprite({ x: targetX, y: targetY, color, energy, isInfected = false, onClick }: MolbotSpriteProps) {
  const bodyRadius = 4 + (Math.min(Math.max(energy, 0), 100) / 100) * 8 // 4–12 px
  const earRadius = bodyRadius * 0.4

  // Reference to the underlying PixiJS Graphics object
  const gRef = useRef<Graphics | null>(null)

  // Current smoothly-interpolated position (starts at server position to avoid initial snap)
  const curRef = useRef({ x: targetX, y: targetY })

  // Latest target position from the server — updated every prop change, no re-render needed
  const targetRef = useRef({ x: targetX, y: targetY })

  // Sync target ref whenever new server data arrives (before the next tick)
  useLayoutEffect(() => {
    targetRef.current.x = targetX
    targetRef.current.y = targetY
  })

  // Smooth movement: lerp current position toward target each animation frame
  useTick((ticker) => {
    const g = gRef.current
    if (!g) return

    // Delta-time correction so speed is consistent regardless of frame-rate
    const t = 1 - Math.pow(1 - LERP, ticker.deltaTime)
    curRef.current.x += (targetRef.current.x - curRef.current.x) * t
    curRef.current.y += (targetRef.current.y - curRef.current.y) * t

    // Write directly to PixiJS object — bypasses React reconciler, no re-render
    g.x = curRef.current.x
    g.y = curRef.current.y

    // Pulsing alpha for infected entities
    if (isInfected) {
      g.alpha = 0.7 + 0.3 * Math.sin(ticker.lastTime * 0.005)
    } else {
      g.alpha = 1.0
    }
  })

  const draw = useCallback(
    (g: Graphics) => {
      g.clear()

      const fillColor = isInfected ? 0x9932cc : color

      // Body
      g.circle(0, 0, bodyRadius)
      g.fill(fillColor)

      // Left ear
      g.circle(-bodyRadius * 0.6, -bodyRadius * 0.85, earRadius)
      g.fill(fillColor)

      // Right ear
      g.circle(bodyRadius * 0.6, -bodyRadius * 0.85, earRadius)
      g.fill(fillColor)
    },
    [bodyRadius, earRadius, color, isInfected],
  )

  return (
    <pixiGraphics
      ref={gRef}
      draw={draw}
      x={curRef.current.x}
      y={curRef.current.y}
      eventMode={onClick ? 'static' : 'none'}
      cursor={onClick ? 'pointer' : undefined}
      onClick={onClick}
    />
  )
}
