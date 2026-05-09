import type { KlineBar } from '@/entities/tick';

export interface IndicatorDefinition {
  type: string;
  label: string;
  defaultParams: Record<string, number>;
  compute: (bars: KlineBar[], params: Record<string, number>) => Array<{ time: number; value: number }>;
  color: string;
}

const registry = new Map<string, IndicatorDefinition>();

export function registerIndicator(def: IndicatorDefinition): void {
  registry.set(def.type, def);
}

export function getIndicator(type: string): IndicatorDefinition | undefined {
  return registry.get(type);
}

export function getAllIndicators(): IndicatorDefinition[] {
  return Array.from(registry.values());
}

registerIndicator({
  type: 'SMA',
  label: 'Simple Moving Average',
  defaultParams: { period: 20 },
  compute: (bars, params) => {
    const period = params.period ?? 20;
    const result: Array<{ time: number; value: number }> = [];
    for (let i = period - 1; i < bars.length; i++) {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) {
        sum += bars[j].close;
      }
      result.push({ time: bars[i].time, value: sum / period });
    }
    return result;
  },
  color: '#F59E0B',
});

registerIndicator({
  type: 'EMA',
  label: 'Exponential Moving Average',
  defaultParams: { period: 20 },
  compute: (bars, params) => {
    const period = params.period ?? 20;
    const k = 2 / (period + 1);
    const result: Array<{ time: number; value: number }> = [];
    let ema = 0;
    for (let i = 0; i < bars.length; i++) {
      if (i < period - 1) {
        ema += bars[i].close;
        continue;
      }
      if (i === period - 1) {
        ema = (ema + bars[i].close) / period;
      } else {
        ema = bars[i].close * k + ema * (1 - k);
      }
      result.push({ time: bars[i].time, value: ema });
    }
    return result;
  },
  color: '#00B4D8',
});

registerIndicator({
  type: 'BOLL',
  label: 'Bollinger Bands',
  defaultParams: { period: 20, stdDev: 2 },
  compute: (bars, params) => {
    const period = params.period ?? 20;
    const stdDevMultiplier = params.stdDev ?? 2;
    const result: Array<{ time: number; value: number }> = [];
    for (let i = period - 1; i < bars.length; i++) {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += bars[j].close;
      const mean = sum / period;
      let variance = 0;
      for (let j = i - period + 1; j <= i; j++) variance += (bars[j].close - mean) ** 2;
      const std = Math.sqrt(variance / period);
      result.push({ time: bars[i].time, value: mean + stdDevMultiplier * std });
    }
    return result;
  },
  color: '#8BA0B4',
});

registerIndicator({
  type: 'VWAP',
  label: 'Volume Weighted Average Price',
  defaultParams: {},
  compute: (bars) => {
    const result: Array<{ time: number; value: number }> = [];
    let cumVolume = 0;
    let cumTPV = 0;
    for (const bar of bars) {
      const tp = (bar.high + bar.low + bar.close) / 3;
      cumTPV += tp * bar.volume;
      cumVolume += bar.volume;
      if (cumVolume > 0) {
        result.push({ time: bar.time, value: cumTPV / cumVolume });
      }
    }
    return result;
  },
  color: '#E8EEF4',
});
