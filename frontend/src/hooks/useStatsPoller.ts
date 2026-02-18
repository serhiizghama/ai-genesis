import { useEffect } from 'react';
import { useWorldStore } from '../store/worldStore';

const POLL_INTERVAL_MS = 2000;

/**
 * Polls /api/stats every 2s and writes avg_energy, resource_count, tps to the store.
 */
export function useStatsPoller(): void {
  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const r = await fetch('/api/stats');
        if (!r.ok || cancelled) return;
        const data = await r.json();
        useWorldStore.getState().setStats({
          avgEnergy: data.avg_energy ?? 0,
          resourceCount: data.resource_count ?? 0,
          tps: data.tps ?? 0,
          predatorKills: data.predator_kills ?? 0,
          virusKills: data.virus_kills ?? 0,
          predatorDeaths: data.predator_deaths ?? 0,
          cycleStage: data.cycle_stage ?? 'idle',
          cycleProblem: data.cycle_problem ?? '',
          cycleSeverity: data.cycle_severity ?? '',
        });
      } catch {
        // ignore
      }
    }

    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);
}
