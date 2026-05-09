import { useEffect, useRef, useState, memo } from 'react';
import {
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  ColorType,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
  type MouseEventParams,
  type ISeriesMarkersPluginApi,
} from 'lightweight-charts';
import { useChartStore } from '@/features/charting';
import type { IndicatorConfig } from '@/features/charting';
import { useStockHistory } from '@/features/market-data';
import type { KlineInterval } from '@/entities/tick';
import { cn } from '@/shared/lib/cn';

const INTERVALS: Array<{ value: KlineInterval; label: string }> = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '1h', label: '1h' },
  { value: '4h', label: '4h' },
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
];

interface TradingChartProps {
  height?: number;
  onCrosshairMove?: (price: number, time: number) => void;
}

export const TradingChart = memo(function TradingChart({ height = 500, onCrosshairMove }: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const overlaySeriesRef = useRef<Map<IndicatorConfig['type'], ISeriesApi<'Line'>>>(new Map());
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const symbol = useChartStore((s) => s.symbol);
  const interval = useChartStore((s) => s.interval);
  const indicators = useChartStore((s) => s.indicators);
  const signals = useChartStore((s) => s.signals);
  const setInterval = useChartStore((s) => s.setInterval);

  const { data: history } = useStockHistory(symbol, interval);

  const [ohlcTooltip, setOhlcTooltip] = useState<{
    open: number; high: number; low: number; close: number; volume: number; time: string;
  } | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#060A0F' },
        textColor: '#8BA0B4',
        fontFamily: "'Inter', system-ui, sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#0F1923' },
        horzLines: { color: '#0F1923' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#2A4A6A', labelBackgroundColor: '#1A2332' },
        horzLine: { color: '#2A4A6A', labelBackgroundColor: '#1A2332' },
      },
      rightPriceScale: { borderColor: '#1E2D3D' },
      timeScale: { borderColor: '#1E2D3D', timeVisible: true, secondsVisible: false },
      handleScroll: true,
      handleScale: true,
    });

    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#00C896',
      downColor: '#FF4D6A',
      borderVisible: false,
      wickUpColor: '#00C896',
      wickDownColor: '#FF4D6A',
    });
    candleSeriesRef.current = candleSeries;

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    volumeSeriesRef.current = volumeSeries;

    markersRef.current = createSeriesMarkers(candleSeries);

    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (!param.time || !param.seriesData) return;
      const candleData = param.seriesData.get(candleSeries) as CandlestickData<Time> | undefined;
      const volData = param.seriesData.get(volumeSeries) as { value: number } | undefined;
      if (candleData) {
        setOhlcTooltip({
          open: candleData.open,
          high: candleData.high,
          low: candleData.low,
          close: candleData.close,
          volume: volData?.value ?? 0,
          time: String(param.time),
        });
        onCrosshairMove?.(candleData.close, Number(param.time));
      }
    });

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!history || !candleSeriesRef.current || !volumeSeriesRef.current) return;

    const candleData: CandlestickData<Time>[] = history.map((bar) => ({
      time: bar.time as Time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    const volumeData = history.map((bar) => ({
      time: bar.time as Time,
      value: bar.volume,
      color: bar.close >= bar.open ? 'rgba(0,200,150,0.3)' : 'rgba(255,77,106,0.3)',
    }));

    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);
  }, [history]);

  useEffect(() => {
    if (!signals.length || !markersRef.current) return;
    markersRef.current.setMarkers(
      signals.map((s) => ({
        time: s.time as Time,
        position: s.position,
        color: s.color,
        shape: s.shape,
        text: s.text,
      }))
    );
  }, [signals]);

  useEffect(() => {
    if (!indicators.length || !chartRef.current) return;

    const existingTypes = new Set(indicators.map((i) => i.type));
    for (const [type, series] of overlaySeriesRef.current.entries()) {
      if (!existingTypes.has(type)) {
        chartRef.current.removeSeries(series);
        overlaySeriesRef.current.delete(type);
      }
    }

    for (const indicator of indicators) {
      if (overlaySeriesRef.current.has(indicator.type)) continue;
      const lineSeries = chartRef.current.addSeries(LineSeries, {
        color: indicator.color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      overlaySeriesRef.current.set(indicator.type, lineSeries);
    }
  }, [indicators]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 px-[var(--space-2)] py-[var(--space-1)] border-b border-[var(--bg-border)]">
        {INTERVALS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setInterval(value)}
            className={cn(
              'px-2 py-0.5 text-[var(--font-size-xs)] rounded-[var(--radius-sm)] transition-colors',
              interval === value
                ? 'bg-[var(--text-accent)] text-[var(--bg-base)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-highlight)]'
            )}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-[var(--font-size-xs)] text-[var(--text-muted)] font-mono">
          {symbol}
        </span>
      </div>

      {ohlcTooltip && (
        <div className="flex items-center gap-[var(--space-3)] px-[var(--space-2)] py-[var(--space-1)] text-[var(--font-size-xs)] font-mono">
          <span className="text-[var(--text-muted)]">O</span>
          <span className="text-[var(--text-primary)]">{ohlcTooltip.open.toFixed(2)}</span>
          <span className="text-[var(--text-muted)]">H</span>
          <span className="text-[var(--text-primary)]">{ohlcTooltip.high.toFixed(2)}</span>
          <span className="text-[var(--text-muted)]">L</span>
          <span className="text-[var(--text-primary)]">{ohlcTooltip.low.toFixed(2)}</span>
          <span className="text-[var(--text-muted)]">C</span>
          <span className={ohlcTooltip.close >= ohlcTooltip.open ? 'text-[var(--color-bid)]' : 'text-[var(--color-ask)]'}>
            {ohlcTooltip.close.toFixed(2)}
          </span>
          <span className="text-[var(--text-muted)]">V</span>
          <span className="text-[var(--text-secondary)]">{ohlcTooltip.volume.toLocaleString()}</span>
        </div>
      )}

      <div ref={containerRef} style={{ height: height - 60 }} />
    </div>
  );
});
