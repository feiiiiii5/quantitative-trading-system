import { useCallback, useRef } from 'react';
import type { Time, IChartApi } from 'lightweight-charts';

type CrosshairTime = Time | null;

export interface CrosshairSyncHandle {
  onCrosshairMove: (t: CrosshairTime, sourceChart: IChartApi) => void;
  registerChart: (chart: IChartApi) => () => void;
}

export function useCrosshairSync(): CrosshairSyncHandle {
  const chartsRef = useRef<Set<IChartApi>>(new Set());
  const syncingRef = useRef(false);

  const onCrosshairMove = useCallback((t: CrosshairTime, sourceChart: IChartApi) => {
    if (syncingRef.current) return;
    syncingRef.current = true;
    try {
      for (const chart of chartsRef.current) {
        if (chart === sourceChart) continue;
        const series = chart.getSeries();
        if (series.length === 0) continue;
        if (t === null) {
          chart.clearCrosshairPosition();
        } else {
          chart.setCrosshairPosition(0, t, series[0]);
        }
      }
    } finally {
      syncingRef.current = false;
    }
  }, []);

  const registerChart = useCallback((chart: IChartApi) => {
    chartsRef.current.add(chart);
    return () => {
      chartsRef.current.delete(chart);
    };
  }, []);

  return { onCrosshairMove, registerChart };
}
