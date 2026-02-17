import { useEffect, useState, useRef } from 'react';
import { useWorldStore } from '../store/worldStore';

/**
 * Entity state from the world stream.
 */
export interface EntityState {
  readonly id: number;
  readonly x: number;
  readonly y: number;
  readonly radius: number;
  readonly color: string;
}

/**
 * World stream state.
 */
export interface WorldStreamState {
  readonly entities: readonly EntityState[];
  readonly tick: number;
  readonly connected: boolean;
}

/**
 * Custom hook to connect to the world WebSocket stream and parse binary protocol.
 *
 * Binary Protocol Format:
 * - Header (6 bytes):
 *   - Tick: uint32 big-endian (4 bytes)
 *   - Count: uint16 big-endian (2 bytes)
 * - Body (20 bytes per entity):
 *   - ID: uint32 big-endian (4 bytes)
 *   - X: float32 big-endian (4 bytes)
 *   - Y: float32 big-endian (4 bytes)
 *   - Radius: float32 big-endian (4 bytes)
 *   - Color: uint32 big-endian (4 bytes)
 *
 * @returns World stream state with entities, tick, and connection status
 */
export function useWorldStream(): WorldStreamState {
  const [entities, setEntities] = useState<readonly EntityState[]>([]);
  const [tick, setTick] = useState<number>(0);
  const [connected, setConnected] = useState<boolean>(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    const connect = () => {
      // Connect to WebSocket directly to backend
      // Note: endpoint is /api/ws/world-stream (with /api prefix)
      const ws = new WebSocket('ws://localhost:8000/api/ws/world-stream');

      // CRITICAL: Set binary type to arraybuffer for binary protocol
      ws.binaryType = 'arraybuffer';

      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[useWorldStream] Connected to world stream');
        setConnected(true);
        useWorldStore.getState().setConnected(true);

        // Clear any pending reconnect
        if (reconnectTimeoutRef.current !== null) {
          clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }
      };

      ws.onmessage = (event: MessageEvent) => {
        // Check if the message is binary
        if (event.data instanceof ArrayBuffer) {
          try {
            const parsedData = parseBinaryFrame(event.data);
            setEntities(parsedData.entities);
            setTick(parsedData.tick);
            useWorldStore.getState().setWorldState(parsedData.tick, parsedData.entities);
          } catch (error) {
            console.error('[useWorldStream] Error parsing binary frame:', error);
          }
        } else {
          console.warn('[useWorldStream] Received non-binary message:', event.data);
        }
      };

      ws.onerror = (error) => {
        console.error('[useWorldStream] WebSocket error:', error);
        setConnected(false);
        useWorldStore.getState().setConnected(false);
      };

      ws.onclose = () => {
        console.log('[useWorldStream] Disconnected from world stream');
        setConnected(false);
        useWorldStore.getState().setConnected(false);
        wsRef.current = null;

        // Attempt to reconnect after 2 seconds
        reconnectTimeoutRef.current = window.setTimeout(() => {
          console.log('[useWorldStream] Attempting to reconnect...');
          connect();
        }, 2000);
      };
    };

    connect();

    // Cleanup on unmount
    return () => {
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return { entities, tick, connected };
}

/**
 * Parse a binary world frame from the server.
 *
 * @param buffer - ArrayBuffer containing the binary frame
 * @returns Parsed tick and entities
 */
function parseBinaryFrame(buffer: ArrayBuffer): { tick: number; entities: EntityState[] } {
  const view = new DataView(buffer);

  // Parse header (6 bytes)
  let offset = 0;

  // Tick: uint32 big-endian
  const tick = view.getUint32(offset, false); // false = big-endian
  offset += 4;

  // Count: uint16 big-endian
  const count = view.getUint16(offset, false);
  offset += 2;

  // Parse entities (20 bytes each)
  const entities: EntityState[] = [];

  for (let i = 0; i < count; i++) {
    // ID: uint32 big-endian
    const id = view.getUint32(offset, false);
    offset += 4;

    // X: float32 big-endian
    const x = view.getFloat32(offset, false);
    offset += 4;

    // Y: float32 big-endian
    const y = view.getFloat32(offset, false);
    offset += 4;

    // Radius: float32 big-endian
    const radius = view.getFloat32(offset, false);
    offset += 4;

    // Color: uint32 big-endian (convert to hex string)
    const colorInt = view.getUint32(offset, false);
    const color = '#' + colorInt.toString(16).padStart(6, '0');
    offset += 4;

    entities.push({ id, x, y, radius, color });
  }

  return { tick, entities };
}
