import { extend } from '@pixi/react'
import { Graphics } from 'pixi.js'
import { useCallback } from 'react'

// Register Graphics so <pixiGraphics> is available as a JSX element
extend({ Graphics })

interface ResourceDotProps {
  /** World X coordinate */
  x: number
  /** World Y coordinate */
  y: number
  /**
   * Energy value of the resource (0–100).
   * Controls alpha: depleted resources appear dimmer.
   */
  energy?: number
}

const RESOURCE_COLOR = 0x00cc44 // green
const DOT_RADIUS = 4

/**
 * ResourceDot — small green circle representing a food resource on the map.
 *
 * Alpha scales with the resource's remaining energy so nearly-empty resources
 * are visually distinct from full ones.
 */
export function ResourceDot({ x, y, energy = 100 }: ResourceDotProps) {
  const alpha = 0.3 + (Math.min(Math.max(energy, 0), 100) / 100) * 0.7 // 0.3–1.0

  const draw = useCallback(
    (g: Graphics) => {
      g.clear()
      g.circle(0, 0, DOT_RADIUS)
      g.fill({ color: RESOURCE_COLOR, alpha })
    },
    [alpha],
  )

  return <pixiGraphics draw={draw} x={x} y={y} />
}
