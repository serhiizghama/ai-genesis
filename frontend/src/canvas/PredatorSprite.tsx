import { extend, useTick } from '@pixi/react'
import { Graphics } from 'pixi.js'
import { useCallback, useLayoutEffect, useRef } from 'react'

extend({ Graphics })

interface PredatorSpriteProps {
  /** World X coordinate (server target) */
  x: number
  /** World Y coordinate (server target) */
  y: number
  /** Optional click handler */
  onClick?: () => void
}

/** Same interpolation constant as MolbotSprite for consistent motion feel. */
const LERP = 0.22

/** Half-size of the diamond shape (visual radius ~15px). */
const SIZE = 15

/**
 * PredatorSprite — PixiJS Graphics sprite for a predator entity.
 *
 * Rendered as a red diamond to distinguish it from the round molbots.
 * Uses the same LERP-based position interpolation as MolbotSprite.
 */
export function PredatorSprite({ x: targetX, y: targetY, onClick }: PredatorSpriteProps) {
  const gRef = useRef<Graphics | null>(null)
  const curRef = useRef({ x: targetX, y: targetY })
  const targetRef = useRef({ x: targetX, y: targetY })

  useLayoutEffect(() => {
    targetRef.current.x = targetX
    targetRef.current.y = targetY
  })

  useTick((ticker) => {
    const g = gRef.current
    if (!g) return

    const t = 1 - Math.pow(1 - LERP, ticker.deltaTime)
    curRef.current.x += (targetRef.current.x - curRef.current.x) * t
    curRef.current.y += (targetRef.current.y - curRef.current.y) * t

    g.x = curRef.current.x
    g.y = curRef.current.y
  })

  const draw = useCallback((g: Graphics) => {
    g.clear()

    // Diamond shape: top, right, bottom, left
    g.moveTo(0, -SIZE)
    g.lineTo(SIZE * 0.65, 0)
    g.lineTo(0, SIZE)
    g.lineTo(-SIZE * 0.65, 0)
    g.closePath()
    g.fill(0xcc0000)

    // Dark outline for visibility
    g.moveTo(0, -SIZE)
    g.lineTo(SIZE * 0.65, 0)
    g.lineTo(0, SIZE)
    g.lineTo(-SIZE * 0.65, 0)
    g.closePath()
    g.stroke({ color: 0x880000, width: 1.5 })
  }, [])

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
