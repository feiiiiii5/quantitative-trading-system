import { createChart as lcCreateChart } from 'lightweight-charts';
import type { IChartApi, ChartOptions } from 'lightweight-charts';
import { colors } from '@/design/tokens/colors';

type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};

export type ChartOptionsDeepPartial = DeepPartial<ChartOptions>;

export function createQuantChart(
  container: HTMLDivElement,
  options: ChartOptionsDeepPartial = {},
): IChartApi {
  return lcCreateChart(container, {
    layout: {
      background: { color: 'transparent' },
      textColor: 'rgba(255,255,255,0.30)',
      fontSize: 11,
      fontFamily: "'SF Mono', 'JetBrains Mono', monospace",
    },
    grid: {
      vertLines: { color: 'rgba(255,255,255,0.04)' },
      horzLines: { color: 'rgba(255,255,255,0.04)' },
    },
    crosshair: {
      mode: 0,
      vertLine: { color: 'rgba(255,255,255,0.15)', labelBackgroundColor: colors.depth[4] },
      horzLine: { color: 'rgba(255,255,255,0.15)', labelBackgroundColor: colors.depth[4] },
    },
    rightPriceScale: {
      borderColor: 'rgba(255,255,255,0.06)',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    timeScale: {
      borderColor: 'rgba(255,255,255,0.06)',
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 5,
      barSpacing: 8,
      minBarSpacing: 3,
    },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true },
    handleScale: { mouseWheel: true, pinch: true },
    ...options,
  } as ChartOptions);
}

export const CANDLE_STYLE = {
  upColor:         colors.market.rise,
  downColor:       colors.market.fall,
  borderUpColor:   colors.market.rise,
  borderDownColor: colors.market.fall,
  wickUpColor:     colors.market.rise,
  wickDownColor:   colors.market.fall,
} as const;

export const VOLUME_STYLE = {
  upColor:   'rgba(255,59,92,0.30)',
  downColor: 'rgba(0,217,160,0.30)',
} as const;
