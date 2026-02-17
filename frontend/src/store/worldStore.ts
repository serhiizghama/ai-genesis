import { create } from 'zustand';
import type { EntityState } from '../hooks/useWorldStream';

export interface FeedMessage {
  readonly id: number;
  readonly agent: string;
  readonly text: string;
  readonly timestamp: number;
}

interface WorldStore {
  entities: readonly EntityState[];
  tick: number;
  entityCount: number;
  isConnected: boolean;
  feedMessages: FeedMessage[];
  selectedEntityId: number | null;

  setWorldState: (tick: number, entities: readonly EntityState[]) => void;
  addFeedMessage: (msg: FeedMessage) => void;
  selectEntity: (id: number | null) => void;
  setConnected: (isConnected: boolean) => void;
}

export const useWorldStore = create<WorldStore>((set) => ({
  entities: [],
  tick: 0,
  entityCount: 0,
  isConnected: false,
  feedMessages: [],
  selectedEntityId: null,

  setWorldState: (tick, entities) => set({ tick, entities, entityCount: entities.length }),

  addFeedMessage: (msg) =>
    set((state) => ({
      feedMessages: [...state.feedMessages.slice(-99), msg],
    })),

  selectEntity: (id) => set({ selectedEntityId: id }),

  setConnected: (isConnected) => set({ isConnected }),
}));
