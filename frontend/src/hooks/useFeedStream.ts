import { useEffect, useRef } from 'react';
import { useWorldStore } from '../store/worldStore';
import type { FeedMetadata } from '../types/feed';

const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const WS_FEED_URL = `${wsProtocol}//${window.location.host}/api/ws/feed`;
const RECONNECT_DELAY_MS = 2000;

interface FeedPayload {
  readonly agent: string;
  readonly action: string;
  readonly message: string;
  readonly metadata?: FeedMetadata;
  readonly timestamp: number;
}

function isFeedMetadata(value: unknown): value is FeedMetadata {
  return typeof value === 'object' && value !== null;
}

function isFeedPayload(data: unknown): data is FeedPayload {
  if (typeof data !== 'object' || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d['agent'] === 'string' &&
    typeof d['message'] === 'string' &&
    typeof d['timestamp'] === 'number'
  );
}

/**
 * Hook that connects to the Evolution Feed WebSocket and adds messages to the world store.
 *
 * Listens for JSON messages: {agent, action, message, metadata, timestamp}
 * Dispatches them to useWorldStore.addFeedMessage with auto-incrementing id.
 * Handles reconnect on disconnect.
 */
export function useFeedStream(): void {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const msgIdRef = useRef<number>(0);

  useEffect(() => {
    const connect = (): void => {
      const ws = new WebSocket(WS_FEED_URL);
      wsRef.current = ws;

      ws.onopen = (): void => {
        console.log('[useFeedStream] Connected to feed stream');
        if (reconnectTimeoutRef.current !== null) {
          clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }
      };

      ws.onmessage = (event: MessageEvent): void => {
        try {
          const parsed: unknown = JSON.parse(event.data as string);
          if (!isFeedPayload(parsed)) {
            console.warn('[useFeedStream] Unexpected message shape:', parsed);
            return;
          }
          msgIdRef.current += 1;
          useWorldStore.getState().addFeedMessage({
            id: msgIdRef.current,
            agent: parsed.agent,
            action: parsed.action,
            message: parsed.message,
            metadata: isFeedMetadata(parsed.metadata) ? parsed.metadata : undefined,
            timestamp: parsed.timestamp,
          });
        } catch (err) {
          console.error('[useFeedStream] Failed to parse message:', err);
        }
      };

      ws.onerror = (): void => {
        console.error('[useFeedStream] WebSocket error');
      };

      ws.onclose = (): void => {
        console.log('[useFeedStream] Disconnected, reconnecting...');
        wsRef.current = null;
        reconnectTimeoutRef.current = window.setTimeout(() => {
          connect();
        }, RECONNECT_DELAY_MS);
      };
    };

    connect();

    return (): void => {
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);
}
