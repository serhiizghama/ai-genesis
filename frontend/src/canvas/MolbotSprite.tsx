import { extend } from '@pixi/react'
import { Graphics } from 'pixi.js'
import { useCallback } from 'react'

// Register Graphics so <pixiGraphics> is available as a JSX element
extend({ Graphics })

interface MolbotSpriteProps {
  /** World X coordinate */
  x: number
  /** World Y coordinate */
  y: number
  /** Fill colour as a 24-bit hex number (e.g. 0xff6633) */
  color: number
  /** Energy level 0–100; controls body radius (4–12 px) */
  energy: number
}

/**
 * MolbotSprite — PixiJS Graphics sprite for a simulation entity.
 *
 * Shape: a filled circle (body) with two smaller circles on top (ears).
 * Body radius scales with energy so healthy creatures appear larger.
 */
export function MolbotSprite({ x, y, color, energy }: MolbotSpriteProps) {
  const bodyRadius = 4 + (Math.min(Math.max(energy, 0), 100) / 100) * 8 // 4–12 px
  const earRadius = bodyRadius * 0.4

  const draw = useCallback(
    (g: Graphics) => {
      g.clear()

      // Body
      g.circle(0, 0, bodyRadius)
      g.fill(color)

      // Left ear
      g.circle(-bodyRadius * 0.6, -bodyRadius * 0.85, earRadius)
      g.fill(color)

      // Right ear
      g.circle(bodyRadius * 0.6, -bodyRadius * 0.85, earRadius)
      g.fill(color)
    },
    [bodyRadius, earRadius, color],
  )

  return <pixiGraphics draw={draw} x={x} y={y} />
}
