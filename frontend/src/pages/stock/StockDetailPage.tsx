import { useEffect, useRef, useState, useCallback, useMemo, memo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { CandlestickSeries, LineSeries, HistogramSeries, type IChartApi, type CandlestickData, type HistogramData, type Time } from 'lightweight-charts';
import { createQuantChart, CANDLE_STYLE } from '@/utils/chartFactory';
import { useStockRealtime, useStockHistory, useStockIndicators } from '@/hooks/queries/useStockQueries';
import { useApiGet } from '@/hooks/useApi';
import { useChipDistribution, useStockNews, useNewsSentiment, useGarchVolatility, useHmmRegime, useRollingRisk, useSeasonality } from '@/hooks/queries/useStockDetailQueries';
import { useCanvas } from '@/hooks/useCanvas';
import { useSSEQuote } from '@/hooks/useSSEQuote';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { EmptyState } from '@/components/ui/EmptyState';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { WaterfallChart } from '@/components/charts/WaterfallChart';
import { formatPrice, formatPercent, formatVolume, formatAmount, safeMin, safeMax } from '@/utils/format';
import type { StockQuote } from '@/types';

interface MoneyFlowRealtime {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
  main_net_inflow: number;
  main_inflow: number;
  main_outflow: number;
  super_large_net: number;
  large_net: number;
  medium_net: number;
  small_net: number;
  main_pct: number;
}

interface MoneyFlowHistoryItem {
  date: string;
  main_inflow: number;
  main_outflow: number;
  main_net_inflow: number;
  super_large_net: number;
  large_net: number;
  medium_net: number;
  small_net: number;
}

interface MoneyFlowData {
  symbol: string;
  realtime: MoneyFlowRealtime;
  history: MoneyFlowHistoryItem[];
  pattern: {
    pattern: string;
    trend: string;
    total_main_net: number;
    avg_main_net: number;
    max_inflow: number;
    max_outflow: number;
  };
}

interface ChipData {
  symbol: string;
  current_price: number;
  avg_cost: number;
  profit_ratio: number;
  concentration: number;
  support_price: number;
  resistance_price: number;
  peak_price: number;
  prices: number[];
  distribution: number[];
  chip_bands: Array<{ range: string; price_low: number; price_high: number; weight: number }>;
  fire: Record<string, unknown>;
}

interface GarchData {
  current_volatility: number;
  long_run_volatility: number;
  persistence: number;
  omega: number;
  alpha: number;
  beta: number;
  forecast_5d: number;
  forecast_10d: number;
  forecast_22d: number;
  forecast_series: Array<{ day: number; volatility_annualized: number }>;
}

interface HmmData {
  current_state: number;
  current_label: string;
  state_probabilities: Record<string, number>;
  states: Array<{
    label: string;
    mean_daily_return: number;
    annualized_volatility: number;
    weight: number;
  }>;
}

interface RollingRiskPoint {
  date: string;
  sharpe: number;
  sortino: number;
  calmar: number;
  volatility: number;
  max_drawdown: number;
  var_95: number;
  cvar_95: number;
  win_rate: number;
}

interface RollingRiskData {
  symbol: string;
  window: number;
  latest: RollingRiskPoint;
  history: RollingRiskPoint[];
}

interface SeasonalityData {
  symbol: string;
  period: string;
  monthly_returns: Record<string, number>;
  day_of_week_returns: Record<string, number>;
  best_month: string;
  worst_month: string;
  best_day: string;
  worst_day: string;
  monthly_sharpe: Record<string, number>;
  turn_of_month_effect: {
    tom_avg_return: number;
    non_tom_avg_return: number;
    tom_win_rate: number;
    non_tom_win_rate: number;
  };
  seasonality_strength: number;
}

interface KlineRaw {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function msToTime(ts: number): Time {
  const d = new Date(ts);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}` as Time;
}

const MoneyFlowTab = memo(function MoneyFlowTab({ symbol }: { symbol: string }) {
  const { data: flowData, loading: isFlowLoading, error: flowError } = useApiGet<MoneyFlowData>(`/moneyflow/stock/${symbol}`);

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!flowData) return;
      ctx.clearRect(0, 0, w, h);

      const history = flowData.history ?? [];
      if (history.length === 0) return;

      const padLeft = 8;
      const padRight = 8;
      const padTop = 28;
      const padBottom = 24;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;
      const barGroupWidth = chartW / history.length;
      const barWidth = Math.max(1, barGroupWidth * 0.35);
      const gap = Math.max(1, barGroupWidth * 0.1);

      ctx.font = '9px monospace';
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.textAlign = 'left';
      ctx.fillText('主力', padLeft, padTop - 10);
      ctx.fillStyle = '#FF1744';
      ctx.fillRect(padLeft + 24, padTop - 16, 8, 8);
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.fillText('散户', padLeft + 40, padTop - 10);
      ctx.fillStyle = '#0A84FF';
      ctx.fillRect(padLeft + 64, padTop - 16, 8, 8);

      const allValues = history.flatMap(d => [d.main_net_inflow, -(d.medium_net + d.small_net)]);
      const maxAbs = Math.max(1, ...allValues.map(Math.abs));
      const zeroY = padTop + chartH / 2;

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, zeroY);
      ctx.lineTo(w - padRight, zeroY);
      ctx.stroke();

      for (let i = 0; i < history.length; i++) {
        const item = history[i]!;
        const x = padLeft + i * barGroupWidth + barGroupWidth / 2;

        const mainH = (item.main_net_inflow / maxAbs) * (chartH / 2);
        ctx.fillStyle = item.main_net_inflow >= 0 ? '#FF1744' : '#00C853';
        if (mainH >= 0) {
          ctx.fillRect(x - barWidth - gap / 2, zeroY - mainH, barWidth, mainH);
        } else {
          ctx.fillRect(x - barWidth - gap / 2, zeroY, barWidth, -mainH);
        }

        const retailNet = -(item.medium_net + item.small_net);
        const retailH = (retailNet / maxAbs) * (chartH / 2);
        ctx.fillStyle = retailNet >= 0 ? '#FF1744' : '#00C853';
        if (retailH >= 0) {
          ctx.fillRect(x + gap / 2, zeroY - retailH, barWidth, retailH);
        } else {
          ctx.fillRect(x + gap / 2, zeroY, barWidth, -retailH);
        }

        if (i % Math.max(1, Math.floor(history.length / 6)) === 0) {
          ctx.fillStyle = 'rgba(255,255,255,0.35)';
          ctx.font = '8px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(item.date.slice(5, 10), x, h - 6);
        }
      }
    }, [flowData]),
    [flowData],
  );

  useEffect(() => { redrawChart(); }, [flowData, redrawChart]);

  if (isFlowLoading) {
    return <SkeletonCard rows={3} />;
  }

  if (flowError || !flowData) {
    return <EmptyState title="资金流向数据暂无" description="请检查网络连接或稍后重试" size="sm" />;
  }

  const rt = flowData.realtime;
  const retailNet = -(rt.medium_net + rt.small_net);

  const waterfallItems = useMemo(() => {
    if (!flowData) return [];
    const r = flowData.realtime;
    return [
      { label: '超大单', value: r.super_large_net ?? 0 },
      { label: '大单', value: r.large_net ?? 0 },
      { label: '中单', value: r.medium_net ?? 0 },
      { label: '小单', value: r.small_net ?? 0 },
      { label: '净流入', value: r.super_large_net + r.large_net + r.medium_net + r.small_net, isTotal: true },
    ];
  }, [flowData]);

  const flowCategories = [
    { label: '超大单', value: rt.super_large_net },
    { label: '大单', value: rt.large_net },
    { label: '中单', value: rt.medium_net },
    { label: '小单', value: rt.small_net },
    { label: '合计', value: rt.main_net_inflow + retailNet },
  ];

  const maxFlow = Math.max(1, ...flowCategories.map(c => Math.abs(c.value)));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <canvas ref={chartRef} style={{ width: '100%', height: '260px', display: 'block' }} />

      {waterfallItems.length > 0 && <WaterfallChart items={waterfallItems} height={240} />}

      <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 140px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>主力净流入</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: rt.main_net_inflow >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
            {rt.main_net_inflow >= 0 ? '+' : ''}{formatAmount(rt.main_net_inflow)}
          </span>
        </div>
        <div style={{ flex: '1 1 140px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>散户净流入</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: retailNet >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
            {retailNet >= 0 ? '+' : ''}{formatAmount(retailNet)}
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {flowCategories.map(cat => {
          const pct = maxFlow > 0 ? (cat.value / maxFlow) * 100 : 0;
          const isPositive = cat.value >= 0;
          return (
            <div key={cat.label} style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)', width: '36px', flexShrink: 0 }}>{cat.label}</span>
              <div style={{ flex: 1, height: '16px', background: 'rgba(255,255,255,0.06)', borderRadius: '2px', overflow: 'hidden', position: 'relative' }}>
                <div style={{
                  position: 'absolute',
                  height: '100%',
                  width: `${Math.abs(pct)}%`,
                  background: isPositive ? '#FF1744' : '#00C853',
                  borderRadius: '2px',
                  opacity: 0.85,
                  left: isPositive ? '50%' : `${50 - Math.abs(pct)}%`,
                }} />
                <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: '1px', background: 'rgba(255,255,255,0.12)' }} />
              </div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: isPositive ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums', width: '72px', textAlign: 'right', flexShrink: 0 }}>
                {cat.value >= 0 ? '+' : ''}{formatAmount(cat.value)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
});

const ChipDistributionTab = memo(function ChipDistributionTab({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useChipDistribution(symbol);
  const chipData = data as unknown as ChipData | undefined;

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!chipData) return;
      ctx.clearRect(0, 0, w, h);

      const dist = chipData.distribution ?? [];
      const prices = chipData.prices ?? [];
      if (dist.length === 0 || prices.length === 0) return;
      const len = Math.min(dist.length, prices.length);

      const padLeft = 52;
      const padRight = 12;
      const padTop = 8;
      const padBottom = 28;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;

      const maxVol = Math.max(1e-10, ...dist.slice(0, len));
      const minPrice = safeMin(prices.slice(0, len));
      const maxPrice = safeMax(prices.slice(0, len));
      const priceRange = Math.max(0.01, maxPrice - minPrice);

      const barHeight = Math.max(2, (chartH / len) * 0.7);
      const barSpacing = chartH / len;

      const currentPrice = chipData.current_price;

      for (let i = 0; i < len; i++) {
        const vol = dist[i]!;
        const price = prices[i]!;
        const y = padTop + i * barSpacing + barSpacing / 2;
        const barW = (vol / maxVol) * chartW;

        const profitPct = currentPrice > 0 ? ((currentPrice - price) / currentPrice) * 100 : 0;
        let color: string;
        if (profitPct > 5) {
          color = '#FF1744';
        } else if (profitPct > 0) {
          color = 'rgba(255,23,68,0.6)';
        } else if (profitPct > -5) {
          color = 'rgba(0,200,83,0.6)';
        } else {
          color = '#00C853';
        }

        ctx.fillStyle = color;
        ctx.fillRect(padLeft, y - barHeight / 2, barW, barHeight);

        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(price.toFixed(2), padLeft - 4, y + 3);
      }

      const avgY = padTop + ((chipData.avg_cost - minPrice) / priceRange) * chartH;
      ctx.strokeStyle = '#0A84FF';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(padLeft, avgY);
      ctx.lineTo(w - padRight, avgY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#0A84FF';
      ctx.font = '8px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`成本 ${chipData.avg_cost.toFixed(2)}`, w - padRight - 64, avgY - 4);

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, padTop);
      ctx.lineTo(padLeft, h - padBottom);
      ctx.stroke();
    }, [chipData]),
    [chipData],
  );

  useEffect(() => { redrawChart(); }, [chipData, redrawChart]);

  if (isLoading) {
    return <SkeletonCard rows={3} />;
  }

  if (isError || !chipData) {
    return <EmptyState title="筹码分布数据暂无" description="请检查网络连接或稍后重试" size="sm" />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 100px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>获利比例</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: '#FF1744', fontVariantNumeric: 'tabular-nums' }}>
            {(chipData.profit_ratio * 100).toFixed(1)}%
          </span>
        </div>
        <div style={{ flex: '1 1 100px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>平均成本</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: 'rgba(255,255,255,0.95)', fontVariantNumeric: 'tabular-nums' }}>
            {chipData.avg_cost.toFixed(2)}
          </span>
        </div>
        <div style={{ flex: '1 1 100px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>集中度</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>
            {(chipData.concentration * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      <canvas ref={chartRef} style={{ width: '100%', height: '300px', display: 'block' }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s4)', justifyContent: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '1px', background: '#FF1744' }} />
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>盈利</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '1px', background: '#00C853' }} />
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>亏损</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '8px', height: '2px', background: '#0A84FF' }} />
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>平均成本</span>
        </div>
      </div>
    </div>
  );
});

const NewsTab = memo(function NewsTab({ symbol }: { symbol: string }) {
  const { data: newsRaw, isLoading: newsLoading, isError: newsError } = useStockNews(symbol);
  const { data: sentiment, isLoading: sentimentLoading, isError: sentimentError } = useNewsSentiment(symbol);
  const news = Array.isArray(newsRaw) ? newsRaw : [];
  const isLoading = newsLoading || sentimentLoading;
  const isError = newsError || sentimentError;

  if (isLoading) {
    return <SkeletonCard rows={3} />;
  }

  if (isError) {
    return <EmptyState title="资讯数据暂无" description="请检查网络连接或稍后重试" size="sm" />;
  }

  const fgIndex = sentiment?.sentiment?.fear_greed_index ?? 50;
  const fgLabel = sentiment?.sentiment?.label ?? '—';
  const summary = sentiment?.summary;

  const gaugeColor = (val: number): string => {
    if (val <= 25) return '#FF1744';
    if (val <= 50) return '#FF9100';
    if (val <= 75) return '#FFD600';
    return '#00C853';
  };

  const sentimentBadgeColor = (label: string): string => {
    if (label === 'positive') return '#FF1744';
    if (label === 'negative') return '#00C853';
    return 'rgba(255,255,255,0.35)';
  };

  const sentimentBadgeText = (label: string): string => {
    if (label === 'positive') return '利好';
    if (label === 'negative') return '利空';
    return '中性';
  };

  const formatTime = (ts: string): string => {
    const d = new Date(Number(ts) * 1000);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>
      {sentiment && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s3)' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>恐惧贪婪指数</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '24px', fontWeight: 700, color: gaugeColor(fgIndex), fontVariantNumeric: 'tabular-nums' }}>{fgIndex.toFixed(0)}</span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: gaugeColor(fgIndex) }}>{fgLabel}</span>
            </div>
            <div style={{ height: '8px', borderRadius: '4px', background: 'rgba(255,255,255,0.06)', position: 'relative', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${fgIndex}%`, background: `linear-gradient(to right, #FF1744, #FF9100, #FFD600, #00C853)`, borderRadius: '4px', opacity: 0.85 }} />
            </div>
          </div>

          {summary && (
            <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>总计</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>{summary.total}</span>
              </div>
              <div style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>利好</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: '#FF1744', fontVariantNumeric: 'tabular-nums' }}>{summary.bullish}</span>
              </div>
              <div style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>利空</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: '#00C853', fontVariantNumeric: 'tabular-nums' }}>{summary.bearish}</span>
              </div>
              <div style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>中性</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.60)', fontVariantNumeric: 'tabular-nums' }}>{summary.neutral}</span>
              </div>
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', maxHeight: '400px', overflowY: 'auto' }}>
        {news.map((item, idx) => (
          <div key={idx} style={{ padding: '10px 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)', marginBottom: '4px' }}>
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontFamily: 'var(--font-sans)', fontSize: '13px', color: 'rgba(255,255,255,0.90)', textDecoration: 'none', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                {item.title}
              </a>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '9px',
                padding: '2px 6px',
                borderRadius: 'var(--r-xs)',
                background: sentimentBadgeColor(item.sentiment_label) === 'rgba(255,255,255,0.35)' ? 'rgba(255,255,255,0.08)' : `${sentimentBadgeColor(item.sentiment_label)}20`,
                color: sentimentBadgeColor(item.sentiment_label),
                flexShrink: 0,
              }}>
                {sentimentBadgeText(item.sentiment_label)}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)', marginBottom: '4px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>{formatTime(item.time)}</span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.25)' }}>{item.source}</span>
            </div>
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.45)', lineHeight: 1.5 }}>
              {item.content.length > 100 ? `${item.content.slice(0, 100)}...` : item.content}
            </div>
          </div>
        ))}
        {news.length === 0 && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', padding: 'var(--s5)', textAlign: 'center' }}>暂无资讯</span>
        )}
      </div>
    </div>
  );
});

const VolatilityTab = memo(function VolatilityTab({ symbol }: { symbol: string }) {
  const { data: garchRaw, isLoading: garchLoading, isError: garchError } = useGarchVolatility(symbol);
  const { data: hmmRaw, isLoading: hmmLoading, isError: hmmError } = useHmmRegime(symbol);
  const garch = garchRaw as unknown as GarchData | undefined;
  const hmm = hmmRaw as unknown as HmmData | undefined;
  const isLoading = garchLoading || hmmLoading;
  const isError = garchError || hmmError;

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!garch) return;
      ctx.clearRect(0, 0, w, h);

      const series = garch.forecast_series ?? [];
      if (series.length === 0) return;

      const padLeft = 48;
      const padRight = 12;
      const padTop = 20;
      const padBottom = 28;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;

      const vols = series.map(s => s.volatility_annualized);
      const minVol = safeMin([...vols, garch.current_volatility]) * 0.9;
      const maxVol = safeMax([...vols, garch.current_volatility]) * 1.1;
      const volRange = Math.max(0.001, maxVol - minVol);

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = padTop + (i / 4) * chartH;
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(w - padRight, y);
        ctx.stroke();

        const val = maxVol - (i / 4) * volRange;
        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${(val * 100).toFixed(1)}%`, padLeft - 4, y + 3);
      }

      const currentY = padTop + ((maxVol - garch.current_volatility) / volRange) * chartH;
      ctx.strokeStyle = '#0A84FF';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(padLeft, currentY);
      ctx.lineTo(w - padRight, currentY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#0A84FF';
      ctx.font = '8px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`当前 ${(garch.current_volatility * 100).toFixed(1)}%`, padLeft + 4, currentY - 4);

      ctx.strokeStyle = '#FF9100';
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < series.length; i++) {
        const x = padLeft + (i / Math.max(1, series.length - 1)) * chartW;
        const y = padTop + ((maxVol - series[i]!.volatility_annualized) / volRange) * chartH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      for (let i = 0; i < series.length; i++) {
        if (i % Math.max(1, Math.floor(series.length / 6)) === 0) {
          const x = padLeft + (i / Math.max(1, series.length - 1)) * chartW;
          ctx.fillStyle = 'rgba(255,255,255,0.35)';
          ctx.font = '8px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(`D${series[i]!.day}`, x, h - 6);
        }
      }
    }, [garch]),
    [garch],
  );

  useEffect(() => { redrawChart(); }, [garch, redrawChart]);

  if (isLoading) {
    return <SkeletonCard rows={4} />;
  }

  if (isError) {
    return <EmptyState title="波动率数据暂无" description="请检查网络连接或稍后重试" size="sm" />;
  }

  const stateBadgeColor = (label: string): { color: string; bg: string } => {
    if (label === 'BULL') return { color: '#FF1744', bg: 'rgba(255,23,68,0.12)' };
    if (label === 'BEAR') return { color: '#00C853', bg: 'rgba(0,200,83,0.12)' };
    return { color: 'rgba(255,255,255,0.60)', bg: 'rgba(255,255,255,0.08)' };
  };

  const stateLabelMap: Record<string, string> = { BULL: '牛市', BEAR: '熊市', NEUTRAL: '震荡' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>
      {garch && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>GARCH 波动率</span>
          <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
            {[
              { label: '当前波动率', value: `${(garch.current_volatility * 100).toFixed(2)}%` },
              { label: '长期波动率', value: `${(garch.long_run_volatility * 100).toFixed(2)}%` },
              { label: '持续性', value: `${(garch.persistence * 100).toFixed(1)}%` },
              { label: '5日预测', value: `${(garch.forecast_5d * 100).toFixed(2)}%` },
              { label: '10日预测', value: `${(garch.forecast_10d * 100).toFixed(2)}%` },
              { label: '22日预测', value: `${(garch.forecast_22d * 100).toFixed(2)}%` },
            ].map(m => (
              <div key={m.label} style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{m.label}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>{m.value}</span>
              </div>
            ))}
          </div>
          <canvas ref={chartRef} style={{ width: '100%', height: '220px', display: 'block' }} />
        </div>
      )}

      {hmm && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>HMM 市场状态</span>

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              fontWeight: 600,
              padding: '3px 10px',
              borderRadius: 'var(--r-xs)',
              color: stateBadgeColor(hmm.current_label).color,
              background: stateBadgeColor(hmm.current_label).bg,
            }}>
              {stateLabelMap[hmm.current_label] ?? hmm.current_label}
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {Object.entries(hmm.state_probabilities).map(([state, prob]) => {
              const badge = stateBadgeColor(state);
              return (
                <div key={state} style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
                  <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: badge.color, width: '40px', flexShrink: 0 }}>{stateLabelMap[state] ?? state}</span>
                  <div style={{ flex: 1, height: '12px', background: 'rgba(255,255,255,0.06)', borderRadius: '2px', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${prob * 100}%`, background: badge.color, borderRadius: '2px', opacity: 0.75 }} />
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.60)', fontVariantNumeric: 'tabular-nums', width: '48px', textAlign: 'right', flexShrink: 0 }}>
                    {(prob * 100).toFixed(1)}%
                  </span>
                </div>
              );
            })}
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
              <thead>
                <tr>
                  {['状态', '日均收益', '年化波动率', '权重'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: 'rgba(255,255,255,0.35)', fontWeight: 400, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {hmm.states.map(st => {
                  const badge = stateBadgeColor(st.label);
                  return (
                    <tr key={st.label}>
                      <td style={{ padding: '6px 8px', color: badge.color, borderBottom: '1px solid rgba(255,255,255,0.04)' }}>{stateLabelMap[st.label] ?? st.label}</td>
                      <td style={{ padding: '6px 8px', color: st.mean_daily_return >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        {st.mean_daily_return >= 0 ? '+' : ''}{(st.mean_daily_return * 100).toFixed(3)}%
                      </td>
                      <td style={{ padding: '6px 8px', color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        {(st.annualized_volatility * 100).toFixed(2)}%
                      </td>
                      <td style={{ padding: '6px 8px', color: 'rgba(255,255,255,0.60)', fontVariantNumeric: 'tabular-nums', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        {(st.weight * 100).toFixed(1)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
});

const RollingRiskTab = memo(function RollingRiskTab({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useRollingRisk(symbol);
  const riskData = data as unknown as RollingRiskData | undefined;

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!riskData) return;
      ctx.clearRect(0, 0, w, h);

      const history = riskData.history ?? [];
      if (history.length === 0) return;

      const padLeft = 48;
      const padRight = 12;
      const padTop = 20;
      const padBottom = 28;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;

      const sharpes = history.map(p => p.sharpe);
      const minSharpe = safeMin([...sharpes, 0]) * 1.1;
      const maxSharpe = safeMax([...sharpes, 0]) * 1.1;
      const sharpeRange = Math.max(0.01, maxSharpe - minSharpe);

      const zeroY = padTop + ((maxSharpe - 0) / sharpeRange) * chartH;
      ctx.strokeStyle = 'rgba(255,255,255,0.15)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(padLeft, zeroY);
      ctx.lineTo(w - padRight, zeroY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = padTop + (i / 4) * chartH;
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(w - padRight, y);
        ctx.stroke();

        const val = maxSharpe - (i / 4) * sharpeRange;
        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(val.toFixed(2), padLeft - 4, y + 3);
      }

      for (let i = 0; i < history.length - 1; i++) {
        const x0 = padLeft + (i / Math.max(1, history.length - 1)) * chartW;
        const x1 = padLeft + ((i + 1) / Math.max(1, history.length - 1)) * chartW;
        const y0 = padTop + ((maxSharpe - history[i]!.sharpe) / sharpeRange) * chartH;
        const y1 = padTop + ((maxSharpe - history[i + 1]!.sharpe) / sharpeRange) * chartH;
        ctx.strokeStyle = history[i]!.sharpe >= 0 ? '#FF1744' : '#00C853';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
      }

      for (let i = 0; i < history.length; i++) {
        if (i % Math.max(1, Math.floor(history.length / 6)) === 0) {
          const x = padLeft + (i / Math.max(1, history.length - 1)) * chartW;
          ctx.fillStyle = 'rgba(255,255,255,0.35)';
          ctx.font = '8px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(history[i]!.date.slice(5, 10), x, h - 6);
        }
      }
    }, [riskData]),
    [riskData],
  );

  useEffect(() => { redrawChart(); }, [riskData, redrawChart]);

  if (isLoading) {
    return <SkeletonCard rows={4} />;
  }

  if (isError || !riskData) {
    return <EmptyState title="滚动风险数据暂无" description="请检查网络连接或稍后重试" size="sm" />;
  }

  const latest = riskData.latest;
  const aColor = (v: number) => v >= 0 ? '#FF1744' : '#00C853';

  const metrics = [
    { label: '夏普率', value: latest.sharpe.toFixed(2), color: aColor(latest.sharpe) },
    { label: '索提诺', value: latest.sortino.toFixed(2), color: aColor(latest.sortino) },
    { label: '卡玛', value: latest.calmar.toFixed(2), color: aColor(latest.calmar) },
    { label: '波动率', value: `${(latest.volatility * 100).toFixed(2)}%`, color: aColor(-latest.volatility) },
    { label: '最大回撤', value: `${(latest.max_drawdown * 100).toFixed(2)}%`, color: aColor(-latest.max_drawdown) },
    { label: 'VaR(95%)', value: `${(latest.var_95 * 100).toFixed(2)}%`, color: aColor(-latest.var_95) },
    { label: 'CVaR(95%)', value: `${(latest.cvar_95 * 100).toFixed(2)}%`, color: aColor(-latest.cvar_95) },
    { label: '胜率', value: `${(latest.win_rate * 100).toFixed(2)}%`, color: aColor(latest.win_rate - 0.5) },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>
      <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        {metrics.map(m => (
          <div key={m.label} style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{m.label}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: m.color, fontVariantNumeric: 'tabular-nums' }}>{m.value}</span>
          </div>
        ))}
      </div>

      <canvas ref={chartRef} style={{ width: '100%', height: '260px', display: 'block' }} />
    </div>
  );
});

const MONTH_ORDER = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_LABELS: Record<string, string> = {
  Jan: '1月', Feb: '2月', Mar: '3月', Apr: '4月', May: '5月', Jun: '6月',
  Jul: '7月', Aug: '8月', Sep: '9月', Oct: '10月', Nov: '11月', Dec: '12月',
};
const DAY_ORDER = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
const DAY_LABELS: Record<string, string> = { Mon: '周一', Tue: '周二', Wed: '周三', Thu: '周四', Fri: '周五' };

const SeasonalityTab = memo(function SeasonalityTab({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useSeasonality(symbol);
  const seasonData = data as unknown as SeasonalityData | undefined;

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!seasonData) return;
      ctx.clearRect(0, 0, w, h);

      const monthlyReturns = seasonData.monthly_returns ?? {};
      const entries = MONTH_ORDER.map(m => ({ month: m, value: monthlyReturns[m] ?? 0 }));
      if (entries.length === 0) return;

      const padLeft = 44;
      const padRight = 12;
      const padTop = 20;
      const padBottom = 28;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;

      const maxAbs = Math.max(0.001, ...entries.map(e => Math.abs(e.value)));
      const zeroY = padTop + chartH / 2;

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, zeroY);
      ctx.lineTo(w - padRight, zeroY);
      ctx.stroke();

      const barGroupWidth = chartW / entries.length;
      const barWidth = Math.max(4, barGroupWidth * 0.55);

      for (let i = 0; i <= 4; i++) {
        const y = padTop + (i / 4) * chartH;
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(w - padRight, y);
        ctx.stroke();

        const val = maxAbs - (i / 4) * 2 * maxAbs;
        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${(val * 100).toFixed(1)}%`, padLeft - 4, y + 3);
      }

      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i]!;
        const x = padLeft + i * barGroupWidth + barGroupWidth / 2;
        const barH = (entry.value / maxAbs) * (chartH / 2);
        const isPositive = entry.value >= 0;
        const isBest = entry.month === seasonData.best_month;
        const isWorst = entry.month === seasonData.worst_month;

        ctx.fillStyle = isPositive ? '#FF1744' : '#00C853';
        if (isBest) ctx.fillStyle = '#FFD600';
        if (isWorst) ctx.fillStyle = '#AA00FF';

        if (isPositive) {
          ctx.fillRect(x - barWidth / 2, zeroY - barH, barWidth, barH);
        } else {
          ctx.fillRect(x - barWidth / 2, zeroY, barWidth, -barH);
        }

        if (isBest) {
          ctx.fillStyle = '#FFD600';
          ctx.font = '10px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('★', x, zeroY - barH - 4);
        }
        if (isWorst) {
          ctx.fillStyle = '#AA00FF';
          ctx.font = '10px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('▼', x, zeroY - barH + (isPositive ? 0 : -barH) - 4);
        }

        ctx.fillStyle = 'rgba(255,255,255,0.45)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(MONTH_LABELS[entry.month] ?? entry.month, x, h - 6);
      }
    }, [seasonData]),
    [seasonData],
  );

  useEffect(() => { redrawChart(); }, [seasonData, redrawChart]);

  if (isLoading) {
    return <SkeletonCard rows={4} />;
  }

  if (isError || !seasonData) {
    return <EmptyState title="季节性数据暂无" description="请检查网络连接或稍后重试" size="sm" />;
  }

  const dayReturns = seasonData.day_of_week_returns ?? {};
  const dayEntries = DAY_ORDER.map(d => ({ day: d, value: dayReturns[d] ?? 0 }));
  const maxDayAbs = Math.max(0.001, ...dayEntries.map(e => Math.abs(e.value)));

  const tom = seasonData.turn_of_month_effect;
  const strengthPct = Math.min(100, Math.max(0, seasonData.seasonality_strength * 100));
  const strengthColor = strengthPct > 60 ? '#FFD600' : strengthPct > 30 ? '#FF9100' : 'rgba(255,255,255,0.45)';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>月度收益</span>
        <canvas ref={chartRef} style={{ width: '100%', height: '260px', display: 'block' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s4)', justifyContent: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '1px', background: '#FF1744' }} />
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>上涨</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '1px', background: '#00C853' }} />
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>下跌</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontFamily: 'sans-serif', fontSize: '10px', color: '#FFD600' }}>★</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>最佳月</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontFamily: 'sans-serif', fontSize: '10px', color: '#AA00FF' }}>▼</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>最差月</span>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>星期效应</span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {dayEntries.map(entry => {
            const pct = maxDayAbs > 0 ? (entry.value / maxDayAbs) * 50 : 0;
            const isPositive = entry.value >= 0;
            const isBest = entry.day === seasonData.best_day;
            const isWorst = entry.day === seasonData.worst_day;
            let barColor = isPositive ? '#FF1744' : '#00C853';
            if (isBest) barColor = '#FFD600';
            if (isWorst) barColor = '#AA00FF';
            return (
              <div key={entry.day} style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: isBest ? '#FFD600' : isWorst ? '#AA00FF' : 'rgba(255,255,255,0.35)', width: '32px', flexShrink: 0 }}>
                  {DAY_LABELS[entry.day] ?? entry.day}
                  {isBest && '★'}
                  {isWorst && '▼'}
                </span>
                <div style={{ flex: 1, height: '16px', background: 'rgba(255,255,255,0.06)', borderRadius: '2px', overflow: 'hidden', position: 'relative' }}>
                  <div style={{
                    position: 'absolute',
                    height: '100%',
                    width: `${Math.abs(pct)}%`,
                    background: barColor,
                    borderRadius: '2px',
                    opacity: 0.85,
                    left: isPositive ? '50%' : `${50 - Math.abs(pct)}%`,
                  }} />
                  <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: '1px', background: 'rgba(255,255,255,0.12)' }} />
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: barColor, fontVariantNumeric: 'tabular-nums', width: '60px', textAlign: 'right', flexShrink: 0 }}>
                  {entry.value >= 0 ? '+' : ''}{(entry.value * 100).toFixed(2)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>换月效应</span>
        <div style={{ display: 'flex', gap: 'var(--s4)' }}>
          <div style={{ flex: 1, padding: 'var(--s4)', borderRadius: 'var(--r-md)', border: '1px solid rgba(255,23,68,0.2)', background: 'rgba(255,23,68,0.06)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#FF1744', fontWeight: 600 }}>换月期</span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>平均收益</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: tom.tom_avg_return >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {tom.tom_avg_return >= 0 ? '+' : ''}{(tom.tom_avg_return * 100).toFixed(3)}%
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>胜率</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: tom.tom_win_rate >= 0.5 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {(tom.tom_win_rate * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          </div>
          <div style={{ flex: 1, padding: 'var(--s4)', borderRadius: 'var(--r-md)', border: '1px solid rgba(0,200,83,0.2)', background: 'rgba(0,200,83,0.06)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#00C853', fontWeight: 600 }}>非换月期</span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>平均收益</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: tom.non_tom_avg_return >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {tom.non_tom_avg_return >= 0 ? '+' : ''}{(tom.non_tom_avg_return * 100).toFixed(3)}%
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>胜率</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: tom.non_tom_win_rate >= 0.5 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {(tom.non_tom_win_rate * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s3)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>季节性强度</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 700, color: strengthColor, fontVariantNumeric: 'tabular-nums' }}>
              {strengthPct.toFixed(0)}
            </span>
          </div>
          <div style={{ height: '6px', borderRadius: '3px', background: 'rgba(255,255,255,0.06)', position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${strengthPct}%`, background: strengthColor, borderRadius: '3px', opacity: 0.75 }} />
          </div>
        </div>
      </div>
    </div>
  );
});

const ChartTooltip = memo(function ChartTooltip({ bar }: { bar: { open: number; high: number; low: number; close: number; volume: number } | null }) {
  if (!bar) return null;
  return (
    <div style={{
      position: 'absolute', top: 12, left: 12, zIndex: 10,
      background: 'var(--glass-2)', border: '1px solid var(--border-default)',
      borderRadius: 8, padding: '8px 12px',
      display: 'grid', gridTemplateColumns: '1fr 1fr',
      gap: '2px 16px', pointerEvents: 'none',
    }}>
      {[['开', bar.open], ['高', bar.high], ['低', bar.low], ['收', bar.close]].map(([label, val]) => (
        <div key={label as string} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
          <span style={{ fontSize: 9, color: 'var(--label-quaternary)', fontFamily: 'var(--font-mono)' }}>{label}</span>
          <span style={{ fontSize: 12, color: 'var(--label-primary)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
            {formatPrice(val as number)}
          </span>
        </div>
      ))}
    </div>
  );
});

const TIME_PERIODS = [
  { key: '1D', label: '1D', count: 1, period: '1min' },
  { key: '1W', label: '1W', count: 5, period: 'daily' },
  { key: '1M', label: '1M', count: 22, period: 'daily' },
  { key: '3M', label: '3M', count: 66, period: 'daily' },
  { key: '1Y', label: '1Y', count: 250, period: 'daily' },
  { key: 'ALL', label: 'ALL', count: 0, period: 'daily' },
] as const;

type TimePeriodKey = typeof TIME_PERIODS[number]['key'];

const KlineChart = memo(function KlineChart({ symbol, period }: { symbol: string; period: TimePeriodKey }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null);
  const volumeSeriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null);
  const [tooltipBar, setTooltipBar] = useState<{ open: number; high: number; low: number; close: number; volume: number } | null>(null);

  const periodConfig = TIME_PERIODS.find(p => p.key === period) ?? TIME_PERIODS[2];
  const { data: klineRaw } = useStockHistory(symbol);
  const klineData = klineRaw as unknown as KlineRaw[] | undefined;

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createQuantChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 480,
      layout: { textColor: 'rgba(255,255,255,0.35)' } as any,
      grid: { vertLines: { color: 'rgba(255,255,255,0.06)' }, horzLines: { color: 'rgba(255,255,255,0.06)' } } as any,
      timeScale: { timeVisible: periodConfig.period === '1min' } as any,
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, CANDLE_STYLE);
    candleSeriesRef.current = candleSeries;

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    volumeSeriesRef.current = volumeSeries;

    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData || param.seriesData.size === 0) {
        setTooltipBar(null);
        return;
      }
      const data = param.seriesData.get(candleSeries) as { open?: number; high?: number; low?: number; close?: number } | undefined;
      const volData = param.seriesData.get(volumeSeries) as { value?: number } | undefined;
      if (data && data.open !== undefined) {
        setTooltipBar({
          open: data.open,
          high: data.high ?? data.open,
          low: data.low ?? data.open,
          close: data.close ?? data.open,
          volume: volData?.value ?? 0,
        });
      } else {
        setTooltipBar(null);
      }
    });

    const onResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [symbol, periodConfig.period]);

  useEffect(() => {
    if (!klineData || !candleSeriesRef.current || !volumeSeriesRef.current || !chartRef.current) return;
    if (Array.isArray(klineData) && klineData.length > 0) {
      const candleData: CandlestickData<Time>[] = [];
      const volData: HistogramData<Time>[] = [];

      for (const d of klineData) {
        const t = msToTime(d.time);
        candleData.push({ time: t, open: d.open, high: d.high, low: d.low, close: d.close });
        const isUp = d.close >= d.open;
        volData.push({
          time: t,
          value: d.volume,
          color: isUp ? 'rgba(255,23,68,0.35)' : 'rgba(0,200,83,0.35)',
        });
      }

      candleSeriesRef.current.setData(candleData);
      volumeSeriesRef.current.setData(volData);
      chartRef.current.timeScale().fitContent();
    }
  }, [klineData]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '480px' }}>
      <ChartTooltip bar={tooltipBar} />
      <div ref={containerRef} style={{ width: '100%', height: '480px' }} />
    </div>
  );
});

interface IndicatorData {
  macd?: Array<{ time: string; macd: number; signal: number; histogram: number }>;
  rsi?: Array<{ time: string; value: number }>;
}

const IndicatorPanel = memo(function IndicatorPanel({ symbol }: { symbol: string }) {
  const [expanded, setExpanded] = useState(false);
  const { data: indicatorsRaw } = useStockIndicators(symbol);
  const data = (indicatorsRaw ?? {}) as unknown as IndicatorData;
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdChartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!expanded || !data.macd?.length) return;
    if (!macdContainerRef.current) return;

    if (macdChartRef.current) { macdChartRef.current.remove(); macdChartRef.current = null; }

    const chart = createQuantChart(macdContainerRef.current, {
      width: macdContainerRef.current.clientWidth,
      height: 140,
      timeScale: { timeVisible: false } as any,
    });
    macdChartRef.current = chart;

    const macdLine = chart.addSeries(LineSeries, {
      color: '#0A84FF',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const signalLine = chart.addSeries(LineSeries, {
      color: '#FF9100',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const histSeries = chart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const macdData = data.macd.map(d => ({ time: d.time as Time, value: d.macd }));
    const signalData = data.macd.map(d => ({ time: d.time as Time, value: d.signal }));
    const histData = data.macd.map(d => ({
      time: d.time as Time,
      value: d.histogram,
      color: d.histogram >= 0 ? 'rgba(255,23,68,0.4)' : 'rgba(0,200,83,0.4)',
    }));

    (macdLine as unknown as { setData: (d: unknown[]) => void }).setData(macdData);
    (signalLine as unknown as { setData: (d: unknown[]) => void }).setData(signalData);
    histSeries.setData(histData);
    chart.timeScale().fitContent();

    const onResize = () => {
      if (macdContainerRef.current) chart.applyOptions({ width: macdContainerRef.current.clientWidth });
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.remove();
      macdChartRef.current = null;
    };
  }, [expanded, data.macd]);

  useEffect(() => {
    if (!expanded || !data.rsi?.length) return;
    if (!rsiContainerRef.current) return;

    if (rsiChartRef.current) { rsiChartRef.current.remove(); rsiChartRef.current = null; }

    const chart = createQuantChart(rsiContainerRef.current, {
      width: rsiContainerRef.current.clientWidth,
      height: 120,
      timeScale: { timeVisible: false } as any,
    });
    rsiChartRef.current = chart;

    const rsiLine = chart.addSeries(LineSeries, {
      color: '#0A84FF',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const rsiData = data.rsi.map(d => ({ time: d.time as Time, value: d.value }));
    (rsiLine as unknown as { setData: (d: unknown[]) => void }).setData(rsiData);
    chart.timeScale().fitContent();

    const onResize = () => {
      if (rsiContainerRef.current) chart.applyOptions({ width: rsiContainerRef.current.clientWidth });
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.remove();
      rsiChartRef.current = null;
    };
  }, [expanded, data.rsi]);

  return (
    <div style={{ borderTop: '1px solid var(--separator)' }}>
      <button
        onClick={() => setExpanded(v => !v)}
        style={{
          width: '100%',
          padding: '8px 16px',
          background: 'transparent',
          border: 'none',
          color: 'var(--label-tertiary)',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          textTransform: 'uppercase' as const,
          letterSpacing: '0.08em',
          cursor: 'pointer',
          textAlign: 'left' as const,
          transition: 'color var(--dur-fast) var(--ease-apple)',
        }}
      >
        {expanded ? '▾' : '▸'} MACD / RSI INDICATORS
      </button>
      {expanded && (
        <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)', marginBottom: 4, letterSpacing: '0.06em' }}>MACD</div>
            <div ref={macdContainerRef} style={{ width: '100%', height: 140 }} />
          </div>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)', marginBottom: 4, letterSpacing: '0.06em' }}>RSI</div>
            <div ref={rsiContainerRef} style={{ width: '100%', height: 120 }} />
          </div>
        </div>
      )}
    </div>
  );
});

function formatPePb(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n) || !Number.isFinite(n)) return '—';
  return n.toFixed(2);
}

function resolveMarketTag(symbol: string): { label: string; color: string; bg: string } {
  if (/^(sh|sz)\d+$/i.test(symbol) || /^\d{6}$/.test(symbol)) {
    if (symbol.startsWith('688')) return { label: '科创板', color: '#FF9100', bg: 'rgba(255,145,0,0.12)' };
    if (symbol.startsWith('3')) return { label: '创业板', color: '#00C853', bg: 'rgba(0,200,83,0.12)' };
    if (symbol.startsWith('6')) return { label: '沪市', color: '#FF1744', bg: 'rgba(255,23,68,0.12)' };
    return { label: '深市', color: '#0A84FF', bg: 'rgba(10,132,255,0.12)' };
  }
  if (/^\d{5}$/.test(symbol)) return { label: '港股', color: '#0A84FF', bg: 'rgba(10,132,255,0.12)' };
  if (/^[A-Z]+$/.test(symbol)) return { label: '美股', color: '#FF9100', bg: 'rgba(255,145,0,0.12)' };
  return { label: 'A股', color: '#FF1744', bg: 'rgba(255,23,68,0.12)' };
}

type ChartTab = 'kline' | 'moneyflow' | 'chip' | 'news' | 'volatility' | 'rolling-risk' | 'seasonality';

const TAB_ITEMS: Array<{ key: ChartTab; label: string }> = [
  { key: 'kline', label: 'K线图' },
  { key: 'moneyflow', label: '资金流向' },
  { key: 'chip', label: '筹码分布' },
  { key: 'news', label: '资讯' },
  { key: 'volatility', label: '波动率' },
  { key: 'rolling-risk', label: '滚动风险' },
  { key: 'seasonality', label: '季节性' },
];

const GLASS: React.CSSProperties = {
  borderRadius: 'var(--r-md)',
  overflow: 'hidden',
  border: '1px solid var(--separator)',
  background: 'var(--bg-glass)',
  backdropFilter: 'blur(24px) saturate(120%)',
};

export function StockDetailPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<ChartTab>('kline');
  const [chartPeriod, setChartPeriod] = useState<TimePeriodKey>('3M');

  const { data: quoteRaw, isLoading, isError: _isError } = useStockRealtime(symbol ?? '');
  const quote = quoteRaw ? (quoteRaw as unknown as StockQuote) : null;

  const { quote: sseQuote } = useSSEQuote(symbol ?? '');
  const liveQuote = useMemo(() => {
    if (!sseQuote || !quote) return quote;
    return { ...quote, price: sseQuote.price, change: sseQuote.change, change_pct: sseQuote.change_pct, volume: sseQuote.volume };
  }, [quote, sseQuote]);

  const handleBack = useCallback(() => {
    navigate(-1);
  }, [navigate]);

  const marketTag = symbol ? resolveMarketTag(symbol) : null;

  if (isLoading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#000000' }}>
        <SkeletonCard rows={5} />
      </div>
    );
  }

  if (!quote) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 'var(--s4)', background: '#000000' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'rgba(255,255,255,0.20)', letterSpacing: '0.06em' }}>
          STOCK NOT FOUND
        </span>
        <button
          onClick={handleBack}
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '12px',
            color: '#0A84FF',
            background: 'rgba(10,132,255,0.12)',
            border: '1px solid rgba(10,132,255,0.25)',
            borderRadius: 'var(--r-sm)',
            padding: '6px 16px',
            cursor: 'pointer',
          }}
        >
          返回
        </button>
      </div>
    );
  }

  if (!liveQuote) return null;

  const isRise = liveQuote.change_pct >= 0;
  const priceClr = isRise ? '#FF1744' : '#00C853';
  const changeBg = isRise ? 'rgba(255,23,68,0.12)' : 'rgba(0,200,83,0.12)';

  const prevClose = liveQuote.last_close ?? liveQuote.close ?? liveQuote.price - liveQuote.change;
  const amplitude = prevClose > 0 ? ((liveQuote.high ?? liveQuote.price) - (liveQuote.low ?? liveQuote.price)) / prevClose * 100 : 0;

  const turnoverDisplay = liveQuote.turnover_rate ?? liveQuote.turnover;
  const metricsLeft = [
    { label: '今开', value: liveQuote.open !== undefined ? formatPrice(liveQuote.open) : '—' },
    { label: '最高', value: liveQuote.high !== undefined ? formatPrice(liveQuote.high) : '—', color: '#FF1744' },
    { label: '成交量', value: formatVolume(liveQuote.volume) },
    { label: '市盈率', value: formatPePb(liveQuote.pe) },
    { label: '换手率', value: turnoverDisplay !== undefined ? `${turnoverDisplay.toFixed(2)}%` : '—' },
  ];

  const metricsRight = [
    { label: '昨收', value: prevClose !== undefined ? formatPrice(prevClose) : '—' },
    { label: '最低', value: liveQuote.low !== undefined ? formatPrice(liveQuote.low) : '—', color: '#00C853' },
    { label: '成交额', value: formatAmount(liveQuote.amount) },
    { label: '市净率', value: formatPePb(liveQuote.pb) },
    { label: '振幅', value: `${amplitude.toFixed(2)}%` },
  ];

  return (
    <div style={{ height: '100%', overflow: 'auto', background: '#000000', padding: 'var(--s6)' }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>

        <button
          onClick={handleBack}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 'var(--s2)',
            fontFamily: 'var(--font-sans)',
            fontSize: '12px',
            color: 'rgba(255,255,255,0.45)',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 0,
            width: 'fit-content',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
          返回
        </button>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--s6)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: '0 0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '24px', fontWeight: 700, color: 'rgba(255,255,255,0.95)', lineHeight: 1.2 }}>
                {liveQuote.name}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>
                {liveQuote.symbol}
              </span>
              {marketTag && (
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '9px',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    padding: '2px 8px',
                    borderRadius: 'var(--r-xs)',
                    background: marketTag.bg,
                    color: marketTag.color,
                  }}
                >
                  {marketTag.label}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s4)' }}>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '42px',
                fontWeight: 700,
                color: priceClr,
                fontVariantNumeric: 'tabular-nums',
                lineHeight: 1,
              }}>
                {formatPrice(liveQuote.price)}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '15px',
                color: priceClr,
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 500,
              }}>
                {liveQuote.change >= 0 ? '+' : ''}{formatPrice(liveQuote.change)}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '14px',
                color: priceClr,
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 600,
                padding: '3px 10px',
                borderRadius: 'var(--r-xs)',
                background: changeBg,
              }}>
                {isRise ? '+' : ''}{formatPercent(liveQuote.change_pct)}
              </span>
            </div>
          </div>

          <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1px', background: 'rgba(255,255,255,0.06)', borderRadius: 'var(--r-md)', overflow: 'hidden', minWidth: 0 }}>
            {metricsLeft.map((row, i) => (
              <div key={`l${i}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: '#0a0a0a' }}>
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>{row.label}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: row.color ?? 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>{row.value}</span>
              </div>
            ))}
            {metricsRight.map((row, i) => (
              <div key={`r${i}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: '#0a0a0a' }}>
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>{row.label}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: row.color ?? 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ ...GLASS }}>
          <div style={{ display: 'flex', borderBottom: '1px solid var(--separator)' }}>
            {TAB_ITEMS.map(tab => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                style={{
                  fontFamily: 'var(--font-sans)',
                  fontSize: '12px',
                  padding: '10px 20px',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: activeTab === tab.key ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.35)',
                  borderBottom: activeTab === tab.key ? '2px solid #0A84FF' : '2px solid transparent',
                  transition: 'color 0.15s, border-color 0.15s',
                  fontWeight: activeTab === tab.key ? 600 : 400,
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === 'kline' && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '8px 16px', borderBottom: '1px solid var(--separator)' }}>
                {TIME_PERIODS.map(tp => (
                  <button
                    key={tp.key}
                    onClick={() => setChartPeriod(tp.key)}
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '11px',
                      fontWeight: chartPeriod === tp.key ? 600 : 400,
                      color: chartPeriod === tp.key ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.35)',
                      background: chartPeriod === tp.key ? 'rgba(10,132,255,0.12)' : 'transparent',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '4px 10px',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    {tp.label}
                  </button>
                ))}
              </div>
              <ErrorBoundary fallback={<div style={{ color: 'var(--label-tertiary)', padding: 16 }}>Chart unavailable</div>}>
                <KlineChart symbol={quote.symbol} period={chartPeriod} />
              </ErrorBoundary>
              <IndicatorPanel symbol={quote.symbol} />
            </>
          )}
          {activeTab === 'moneyflow' && (
            <div style={{ padding: 'var(--s5)' }}>
              <MoneyFlowTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'chip' && (
            <div style={{ padding: 'var(--s5)' }}>
              <ChipDistributionTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'news' && (
            <div style={{ padding: 'var(--s5)' }}>
              <NewsTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'volatility' && (
            <div style={{ padding: 'var(--s5)' }}>
              <VolatilityTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'rolling-risk' && (
            <div style={{ padding: 'var(--s5)' }}>
              <RollingRiskTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'seasonality' && (
            <div style={{ padding: 'var(--s5)' }}>
              <SeasonalityTab symbol={quote.symbol} />
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--s5)' }}>
          <div style={{ ...GLASS, padding: 'var(--s5)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', marginBottom: 'var(--s3)', textTransform: 'uppercase' }}>
              价格区间
            </div>
            <PriceRangeBar high={liveQuote.high ?? liveQuote.price} low={liveQuote.low ?? liveQuote.price} current={liveQuote.price} prevClose={prevClose} />
          </div>

          <div style={{ ...GLASS, padding: 'var(--s5)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', marginBottom: 'var(--s3)', textTransform: 'uppercase' }}>
              成交概览
            </div>
            <VolumeOverview volume={liveQuote.volume} amount={liveQuote.amount} turnover={liveQuote.turnover} />
          </div>
        </div>

      </div>
    </div>
  );
}

function PriceRangeBar({ high, low, current, prevClose }: { high: number; low: number; current: number; prevClose: number }) {
  const range = high - low;
  const safeRange = range > 0 ? range : 1;
  const currentPct = ((current - low) / safeRange) * 100;
  const prevPct = prevClose > 0 ? ((prevClose - low) / safeRange) * 100 : 50;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#00C853', fontVariantNumeric: 'tabular-nums' }}>{formatPrice(low)}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.35)', fontVariantNumeric: 'tabular-nums' }}>昨收 {formatPrice(prevClose)}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#FF1744', fontVariantNumeric: 'tabular-nums' }}>{formatPrice(high)}</span>
      </div>
      <div style={{ position: 'relative', height: '8px', background: 'rgba(255,255,255,0.06)', borderRadius: '4px', overflow: 'hidden' }}>
        <div style={{
          position: 'absolute',
          left: `${Math.min(prevPct, currentPct)}%`,
          width: `${Math.abs(currentPct - prevPct)}%`,
          top: 0,
          bottom: 0,
          background: current >= prevClose ? '#FF1744' : '#00C853',
          borderRadius: '4px',
          opacity: 0.6,
        }} />
        <div style={{
          position: 'absolute',
          left: `${prevPct}%`,
          top: '-2px',
          bottom: '-2px',
          width: '2px',
          background: 'rgba(255,255,255,0.35)',
          borderRadius: '1px',
        }} />
        <div style={{
          position: 'absolute',
          left: `${currentPct}%`,
          top: '-3px',
          bottom: '-3px',
          width: '3px',
          background: current >= prevClose ? '#FF1744' : '#00C853',
          borderRadius: '2px',
          boxShadow: current >= prevClose ? '0 0 6px rgba(255,23,68,0.5)' : '0 0 6px rgba(0,200,83,0.5)',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.20)' }}>LOW</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.20)' }}>HIGH</span>
      </div>
    </div>
  );
}

function VolumeOverview({ volume, amount, turnover }: { volume: number; amount: number; turnover?: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>成交量</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>
          {formatVolume(volume)}
        </span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>成交额</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>
          {formatAmount(amount)}
        </span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>换手率</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: turnover !== undefined && turnover > 5 ? '#FF9100' : 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>
          {turnover !== undefined ? `${turnover.toFixed(2)}%` : '—'}
        </span>
      </div>
    </div>
  );
}
