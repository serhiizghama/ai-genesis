import { create } from 'zustand';
import type { EntityState } from '../hooks/useWorldStream';
import type { FeedMessage } from '../types/feed';

export type { FeedMessage };

interface StatsSnapshot {
  avgEnergy: number;
  resourceCount: number;
  tps: number;
}

interface WorldStore {
  entities: readonly EntityState[];
  tick: number;
  entityCount: number;
  isConnected: boolean;
  feedMessages: FeedMessage[];
  selectedEntityId: number | null;
  stats: StatsSnapshot;

  setWorldState: (tick: number, entities: readonly EntityState[]) => void;
  addFeedMessage: (msg: FeedMessage) => void;
  selectEntity: (id: number | null) => void;
  setConnected: (isConnected: boolean) => void;
  setStats: (s: StatsSnapshot) => void;
}

export const useWorldStore = create<WorldStore>((set) => ({
  entities: [],
  tick: 0,
  entityCount: 0,
  isConnected: false,
  feedMessages: [],
  selectedEntityId: null,
  stats: { avgEnergy: 0, resourceCount: 0, tps: 0 },

  setWorldState: (tick, entities) => set({ tick, entities, entityCount: entities.length }),

  addFeedMessage: (msg) =>
    set((state) => ({
      feedMessages: [...state.feedMessages.slice(-99), msg],
    })),

  selectEntity: (id) => set({ selectedEntityId: id }),

  setConnected: (isConnected) => set({ isConnected }),

  setStats: (stats) => set({ stats }),
}));
