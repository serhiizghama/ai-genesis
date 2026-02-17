import { Application } from '@pixi/react'
import { useRef, type ReactNode } from 'react'

interface PixiAppProps {
  children?: ReactNode
}

/**
 * PixiApp — full-screen PixiJS application container.
 *
 * Wraps @pixi/react's Application component and sizes it to fill its parent.
 * The black background matches the simulation's dark aesthetic.
 */
export function PixiApp({ children }: PixiAppProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', overflow: 'hidden' }}
    >
      <Application
        background="#0a0a0f"
        antialias
        resizeTo={containerRef}
      >
        {children}
      </Application>
    </div>
  )
}
