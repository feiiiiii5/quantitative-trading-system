import type { KlineInterval } from '@/entities/tick';

export interface IndicatorConfig {
  type: 'SMA' | 'EMA' | 'BOLL' | 'VWAP';
  params: Record<string, number>;
  color: string;
}

export interface SignalMarker {
  time: number;
  position: 'belowBar' | 'aboveBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

export interface ChartState {
  symbol: string;
  interval: KlineInterval;
  indicators: IndicatorConfig[];
  signals: SignalMarker[];
  setSymbol: (symbol: string) => void;
  setInterval: (interval: KlineInterval) => void;
  addIndicator: (indicator: IndicatorConfig) => void;
  removeIndicator: (type: string) => void;
  setSignals: (signals: SignalMarker[]) => void;
}
