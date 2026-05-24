import { describe, it, expect, vi } from 'vitest';
import type { IChartApi } from 'lightweight-charts';

const mockChartApi: IChartApi = {
  addCandlestickSeries: vi.fn(),
  addHistogramSeries: vi.fn(),
  addLineSeries: vi.fn(),
  addAreaSeries: vi.fn(),
  addBaselineSeries: vi.fn(),
  removeSeries: vi.fn(),
  resize: vi.fn(),
  applyOptions: vi.fn(),
  options: vi.fn(),
  takeScreenshot: vi.fn(),
  timeScale: vi.fn(),
  priceScale: vi.fn(),
  subscribeCrosshairMove: vi.fn(),
  unsubscribeCrosshairMove: vi.fn(),
  subscribeClick: vi.fn(),
  unsubscribeClick: vi.fn(),
  destroy: vi.fn(),
} as unknown as IChartApi;

vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => mockChartApi),
}));

vi.mock('@/design/tokens/colors', () => ({
  colors: {
    market: {
      rise: '#FF3B5C',
      fall: '#00D9A0',
      riseWeak: 'rgba(255,59,92,0.15)',
      fallWeak: 'rgba(0,217,160,0.15)',
      riseDim: 'rgba(255,59,92,0.06)',
      fallDim: 'rgba(0,217,160,0.06)',
      neutral: 'rgba(255,255,255,0.40)',
    },
    depth: {
      0: '#000000',
      1: '#0A0A0F',
      2: '#111118',
      3: '#18181F',
      4: '#1F1F28',
      5: '#26262F',
    },
  },
}));

import { createQuantChart, CANDLE_STYLE, VOLUME_STYLE } from './chartFactory';
import { createChart } from 'lightweight-charts';

describe('createQuantChart', () => {
  it('returns an IChartApi', () => {
    const container = document.createElement('div');
    const chart = createQuantChart(container);
    expect(chart).toBe(mockChartApi);
  });

  it('calls createChart with container and options', () => {
    const container = document.createElement('div');
    createQuantChart(container);
    expect(createChart).toHaveBeenCalledWith(container, expect.any(Object));
  });

  it('merges user options into defaults', () => {
    const container = document.createElement('div');
    createQuantChart(container, { crosshair: { mode: 1 } as any });
    expect(createChart).toHaveBeenCalledWith(
      container,
      expect.objectContaining({
        crosshair: { mode: 1 },
      }),
    );
  });
});

describe('CANDLE_STYLE', () => {
  it('has upColor from market.rise', () => {
    expect(CANDLE_STYLE.upColor).toBe('#FF3B5C');
  });

  it('has downColor from market.fall', () => {
    expect(CANDLE_STYLE.downColor).toBe('#00D9A0');
  });

  it('has borderUpColor from market.rise', () => {
    expect(CANDLE_STYLE.borderUpColor).toBe('#FF3B5C');
  });

  it('has borderDownColor from market.fall', () => {
    expect(CANDLE_STYLE.borderDownColor).toBe('#00D9A0');
  });

  it('has wickUpColor from market.rise', () => {
    expect(CANDLE_STYLE.wickUpColor).toBe('#FF3B5C');
  });

  it('has wickDownColor from market.fall', () => {
    expect(CANDLE_STYLE.wickDownColor).toBe('#00D9A0');
  });
});

describe('VOLUME_STYLE', () => {
  it('has upColor as semi-transparent rise', () => {
    expect(VOLUME_STYLE.upColor).toBe('rgba(255,59,92,0.30)');
  });

  it('has downColor as semi-transparent fall', () => {
    expect(VOLUME_STYLE.downColor).toBe('rgba(0,217,160,0.30)');
  });
});
