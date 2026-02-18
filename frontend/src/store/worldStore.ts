import { create } from 'zustand';
import type { EntityState, ResourceState } from '../hooks/useWorldStream';
import type { FeedMessage } from '../types/feed';

export type { FeedMessage, ResourceState };

interface StatsSnapshot {
  avgEnergy: number;
  resourceCount: number;
  tps: number;
  predatorKills: number;
  virusKills: number;
  predatorDeaths: number;
  cycleStage: string;
  cycleProblem: string;
  cycleSeverity: string;
}

interface WorldStore {
  entities: readonly EntityState[];
  resources: readonly ResourceState[];
  tick: number;
  entityCount: number;
  isConnected: boolean;
  feedMessages: FeedMessage[];
  selectedEntityId: number | null;
  stats: StatsSnapshot;

  setWorldState: (tick: number, entities: readonly EntityState[], resources: readonly ResourceState[]) => void;
  addFeedMessage: (msg: FeedMessage) => void;
  selectEntity: (id: number | null) => void;
  setConnected: (isConnected: boolean) => void;
  setStats: (s: StatsSnapshot) => void;
}

export const useWorldStore = create<WorldStore>((set) => ({
  entities: [],
  resources: [],
  tick: 0,
  entityCount: 0,
  isConnected: false,
  feedMessages: [],
  selectedEntityId: null,
  stats: { avgEnergy: 0, resourceCount: 0, tps: 0, predatorKills: 0, virusKills: 0, predatorDeaths: 0, cycleStage: 'idle', cycleProblem: '', cycleSeverity: '' },

  setWorldState: (tick, entities, resources) => set({ tick, entities, resources, entityCount: entities.length }),

  addFeedMessage: (msg) =>
    set((state) => ({
      feedMessages: [...state.feedMessages.slice(-99), msg],
    })),

  selectEntity: (id) => set({ selectedEntityId: id }),

  setConnected: (isConnected) => set({ isConnected }),

  setStats: (stats) => set({ stats }),
}));
