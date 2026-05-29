import { useState, useEffect, useRef, useCallback, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { CandlestickSeries, type IChartApi, type ISeriesApi, type CandlestickData, type Time } from 'lightweight-charts';
import { createQuantChart, CANDLE_STYLE } from '@/utils/chartFactory';
import { apiGet } from '@/api/client';
import { formatPrice, formatPercent, formatVolume, formatAmount, priceColor } from '@/utils/format';
import type { StockQuote } from '@/types';

export const RISE_HEX = '#FF1744';
export const FALL_HEX = '#00C853';
export const ACCENT_HEX = '#0A84FF';

export function formatPePb(n: number | undefined): string {
  if (n === undefined || n === null || Number.isNaN(n) || !Number.isFinite(n)) return '—';
  return n.toFixed(1);
}

export function changeColor(val: number): string {
  if (val > 0) return RISE_HEX;
  if (val < 0) return FALL_HEX;
  return 'rgba(255,255,255,0.45)';
}

export const TickFlashCell = memo(function TickFlashCell({ value, changePct }: { value: number; changePct: number }) {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const prev = useRef(value);
  useEffect(() => {
    if (value !== prev.current) {
      setFlash(value > prev.current ? 'up' : 'down');
      prev.current = value;
      const timer = setTimeout(() => setFlash(null), 500);
      return () => clearTimeout(timer);
    }
  }, [value]);
  return (
    <span style={{
      color: changePct >= 0 ? 'var(--num-positive)' : 'var(--num-negative)',
      background: flash === 'up' ? 'rgba(255,59,92,0.15)' :
                  flash === 'down' ? 'rgba(0,217,160,0.15)' : 'transparent',
      transition: 'background 500ms ease-out',
      fontVariantNumeric: 'tabular-nums',
      fontFamily: 'var(--font-mono)',
    }}>
      {formatPrice(value)}
    </span>
  );
});

export const LimitBadge = memo(function LimitBadge({ changePct }: { changePct: number }) {
  if (changePct >= 9.9) {
    return (
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '9px',
        fontWeight: 600,
        padding: '1px 4px',
        borderRadius: '2px',
        background: 'rgba(255,23,68,0.2)',
        color: '#FF1744',
        marginLeft: 4,
        flexShrink: 0,
      }}>
        ↑停
      </span>
    );
  }
  if (changePct <= -9.9) {
    return (
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '9px',
        fontWeight: 600,
        padding: '1px 4px',
        borderRadius: '2px',
        background: 'rgba(0,200,83,0.2)',
        color: '#00C853',
        marginLeft: 4,
        flexShrink: 0,
      }}>
        ↓停
      </span>
    );
  }
  return null;
});

export const KlineChart = memo(function KlineChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    const chart = createQuantChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 200,
      layout: { textColor: 'rgba(255,255,255,0.35)' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.06)' }, horzLines: { color: 'rgba(255,255,255,0.06)' } },
    });
    const series = chart.addSeries(CandlestickSeries, CANDLE_STYLE);
    chartRef.current = chart;
    seriesRef.current = series;

    const loadKline = async () => {
      try {
        const data = await apiGet<Array<{
          time: number;
          open: number;
          high: number;
          low: number;
          close: number;
          volume?: number;
        }>>(`/market/kline`, { symbol, period: 'daily', count: 120 });
        if (cancelled) return;
        if (Array.isArray(data) && data.length > 0) {
          const candleData: CandlestickData<Time>[] = data.map(d => {
            const dt = new Date(d.time);
            const yyyy = dt.getFullYear();
            const mm = String(dt.getMonth() + 1).padStart(2, '0');
            const dd = String(dt.getDate()).padStart(2, '0');
            return {
              time: `${yyyy}-${mm}-${dd}` as Time,
              open: d.open,
              high: d.high,
              low: d.low,
              close: d.close,
            };
          });
          series.setData(candleData);
          chart.timeScale().fitContent();
        }
      } catch {
        if (!cancelled && seriesRef.current) {
          seriesRef.current.setData([]);
        }
      }
    };
    loadKline();

    const onResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', onResize);
    return () => {
      cancelled = true;
      window.removeEventListener('resize', onResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [symbol]);

  return <div ref={containerRef} style={{ width: '100%', height: '200px' }} />;
});

export const SkeletonRow = memo(function SkeletonRow({ style }: { style: React.CSSProperties }) {
  return (
    <div style={{ ...style, display: 'flex', alignItems: 'center', gap: 'var(--s3)', padding: '0 var(--s4)' }}>
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} style={{
          width: i === 1 ? '60px' : '48px',
          height: '10px',
          borderRadius: 'var(--r-xs)',
          background: 'var(--separator)',
          animation: 'market-pulse 1.2s ease-in-out infinite',
          animationDelay: `${i * 80}ms`,
        }} />
      ))}
    </div>
  );
});

export const LoadingState = memo(function LoadingState() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100%',
      gap: 'var(--s4)',
    }}>
      <span style={{
        fontFamily: 'var(--font-sans)',
        fontSize: '48px',
        fontWeight: 300,
        color: 'var(--accent)',
        lineHeight: 1,
      }}>
        Q
      </span>
      <div style={{ width: '200px' }}>
        {Array.from({ length: 5 }, (_, i) => (
          <SkeletonRow key={i} style={{ height: '40px', position: 'relative' }} />
        ))}
      </div>
    </div>
  );
});

export const DrawerBackdrop = memo(function DrawerBackdrop({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  const handleBackdrop = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  }, [onClose]);

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 10,
        background: 'rgba(0,0,0,0.4)',
        backdropFilter: 'blur(4px)',
        animation: 'fade-in var(--dur-fast) var(--ease-apple)',
      }}
      onClick={handleBackdrop}
    >
      {children}
    </div>
  );
});

export const StockDrawer = memo(function StockDrawer({
  stock,
  onClose,
  isWatched,
  onToggleWatch,
}: {
  stock: StockQuote;
  onClose: () => void;
  isWatched: boolean;
  onToggleWatch: (e: React.MouseEvent) => void;
}) {
  const navigate = useNavigate();
  return (
    <div
      style={{
        position: 'absolute',
        right: 0,
        top: 0,
        bottom: 0,
        width: '320px',
        background: 'var(--bg-glass)',
        backdropFilter: 'blur(24px) saturate(120%)',
        borderLeft: '1px solid var(--separator)',
        boxShadow: 'var(--shadow-lg)',
        display: 'flex',
        flexDirection: 'column',
        animation: 'slide-in-right var(--dur-base) var(--ease-spring)',
      }}
      onClick={e => e.stopPropagation()}
    >
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: 'var(--s4) var(--s5)',
        borderBottom: '1px solid var(--separator)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '16px', fontWeight: 600, color: 'var(--label-primary)', lineHeight: 1.2 }}>{stock.name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent)', fontVariantNumeric: 'tabular-nums' }}>{stock.symbol}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s2)' }}>
          <button
            onClick={() => navigate(`/stock/${stock.symbol}`)}
            style={{
              background: 'none',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-sm)',
              color: 'var(--accent)',
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              cursor: 'pointer',
              height: '28px',
              padding: '0 10px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: `all var(--dur-fast) var(--ease-apple)`,
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--separator)'; }}
          >
            详情
          </button>
          <button
            onClick={onToggleWatch}
            style={{
              background: 'none',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-sm)',
              color: isWatched ? 'var(--signal-warn)' : 'var(--label-tertiary)',
              fontSize: '14px',
              cursor: 'pointer',
              width: '28px',
              height: '28px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: `all var(--dur-fast) var(--ease-apple)`,
            }}
          >
            {isWatched ? '★' : '☆'}
          </button>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-sm)',
              color: 'var(--label-tertiary)',
              fontSize: '14px',
              cursor: 'pointer',
              width: '28px',
              height: '28px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: `all var(--dur-fast) var(--ease-apple)`,
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--label-primary)'; e.currentTarget.style.borderColor = 'var(--separator-hi)'; }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--label-tertiary)'; e.currentTarget.style.borderColor = 'var(--separator)'; }}
          >
            ✕
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 'var(--s5)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s3)', marginBottom: 'var(--s4)' }}>
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '28px',
            fontWeight: 600,
            color: priceColor(stock.change_pct),
            fontVariantNumeric: 'tabular-nums',
            lineHeight: 1,
          }}>
            {formatPrice(stock.price)}
          </span>
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '14px',
            color: priceColor(stock.change_pct),
            fontVariantNumeric: 'tabular-nums',
            fontWeight: 500,
            padding: '2px 8px',
            borderRadius: 'var(--r-xs)',
            background: stock.change_pct >= 0 ? 'var(--rise-bg)' : 'var(--fall-bg)',
          }}>
            {formatPercent(stock.change_pct)}
          </span>
        </div>

        <div style={{
          marginBottom: 'var(--s4)',
          borderRadius: 'var(--r-md)',
          overflow: 'hidden',
          border: '1px solid var(--separator)',
          background: 'var(--bg-elevated)',
        }}>
          <KlineChart symbol={stock.symbol} />
        </div>

        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '9px',
          color: 'var(--label-tertiary)',
          letterSpacing: '0.08em',
          marginBottom: 'var(--s2)',
          textTransform: 'uppercase',
        }}>
          基本面
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '1px',
          background: 'var(--separator)',
          borderRadius: 'var(--r-md)',
          overflow: 'hidden',
        }}>
          {([
            { label: '成交量', value: formatVolume(stock.volume) },
            { label: '成交额', value: formatAmount(stock.amount) },
            { label: '市盈率', value: formatPePb(stock.pe) },
            { label: '市净率', value: formatPePb(stock.pb) },
            { label: '今开', value: stock.open !== undefined ? formatPrice(stock.open) : '—' },
            { label: '最高', value: stock.high !== undefined ? formatPrice(stock.high) : '—' },
            { label: '最低', value: stock.low !== undefined ? formatPrice(stock.low) : '—' },
            { label: '昨收', value: stock.close !== undefined ? formatPrice(stock.close) : '—' },
          ]).map(row => (
            <div key={row.label} style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px var(--s3)',
              background: 'var(--bg-elevated)',
            }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--label-tertiary)', letterSpacing: '0.04em' }}>{row.label}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>{row.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});
