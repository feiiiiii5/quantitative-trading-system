import { useEffect, useState } from 'react';
import { apiGet } from '@/api/client';
import { formatPrice, formatPercent, formatAmount, priceColor } from '@/utils/format';
import type { StockQuote, IndexQuote, SectorData } from '@/types';

const DEFAULT_INDICES: IndexQuote[] = [
  { name: '上证指数', code: 'sh000001', price: 0, change: 0, change_pct: 0 },
  { name: '深证成指', code: 'sz399001', price: 0, change: 0, change_pct: 0 },
  { name: '创业板指', code: 'sz399006', price: 0, change: 0, change_pct: 0 },
  { name: '沪深300', code: 'sh000300', price: 0, change: 0, change_pct: 0 },
  { name: '中证500', code: 'sh000905', price: 0, change: 0, change_pct: 0 },
  { name: '科创50', code: 'sh000688', price: 0, change: 0, change_pct: 0 },
];

interface MarketBreadth {
  advance_count: number;
  decline_count: number;
  flat_count: number;
  total_amount: number;
}

function MiniSparkline({ changePct }: { changePct: number }) {
  const width = 50;
  const height = 14;
  const points = Array.from({ length: 16 }, (_, i) => {
    const t = i / 15;
    const trend = changePct > 0 ? 0.4 * t : changePct < 0 ? -0.4 * t : 0;
    const wave1 = Math.sin(i * 1.8 + changePct * 8) * 0.25;
    const wave2 = Math.sin(i * 3.1 + changePct * 4) * 0.12;
    const wave3 = Math.cos(i * 0.7 + changePct * 12) * 0.08;
    return trend + wave1 + wave2 + wave3;
  });
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const color = changePct >= 0 ? 'var(--signal-rise)' : 'var(--signal-fall)';

  const pathParts = points.map((p, i) => {
    const x = (i / (points.length - 1)) * width;
    const y = height - 1 - ((p - min) / range) * (height - 2);
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  });

  let smoothPath = pathParts[0];
  for (let i = 1; i < pathParts.length; i++) {
    smoothPath += ` ${pathParts[i]}`;
  }

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ flexShrink: 0 }}>
      <path d={smoothPath} fill="none" stroke={color} strokeWidth="1.2" opacity="0.55" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const panelStyle: React.CSSProperties = {
  background: '#0a0a0a',
  borderRadius: '8px',
  border: '1px solid rgba(255,255,255,0.04)',
  boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
  overflow: 'hidden',
};

const panelTitleStyle: React.CSSProperties = {
  fontFamily: "var(--font-display)",
  fontSize: '18px',
  color: 'var(--accent)',
  fontWeight: 500,
  padding: '16px 20px',
  borderBottom: '1px solid rgba(255,255,255,0.04)',
};

function SectorHeatmap({ sectors }: { sectors: SectorData[] }) {
  const maxAbs = Math.max(...sectors.map(s => Math.abs(s.change_pct ?? 0)), 0.01);

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', padding: '16px 20px' }}>
      {sectors.slice(0, 30).map((sec) => {
        const pct = sec.change_pct ?? 0;
        const norm = Math.min(Math.abs(pct) / Math.max(maxAbs, 0.01), 1);
        const isRise = pct >= 0;
        const baseR = isRise ? 212 : 78;
        const baseG = isRise ? 88 : 158;
        const baseB = isRise ? 74 : 110;
        const opacity = 0.12 + norm * 0.55;

        return (
          <div key={sec.name} style={{
            padding: '8px 12px',
            borderRadius: '4px',
            background: `rgba(${baseR},${baseG},${baseB},${opacity})`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            minWidth: '60px',
            flex: '1 1 auto',
            cursor: 'default',
            transition: 'transform 120ms ease-out, box-shadow 120ms ease-out',
          }}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = 'translateY(-1px)';
              e.currentTarget.style.boxShadow = `0 4px 12px rgba(${baseR},${baseG},${baseB},${opacity * 0.3})`;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = 'none';
            }}
            title={`${sec.name} | ${formatPercent(pct)} | ${formatAmount(sec.amount ?? 0)}`}
          >
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.9)', whiteSpace: 'nowrap' }}>{sec.name}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.7)', fontVariantNumeric: 'tabular-nums', marginTop: '2px' }}>{formatPercent(pct)}</span>
          </div>
        );
      })}
    </div>
  );
}

function BreadthBar({ breadth }: { breadth: MarketBreadth | null }) {
  if (!breadth) return null;
  const total = breadth.advance_count + breadth.decline_count + breadth.flat_count;
  if (total === 0) return null;
  const advanceW = (breadth.advance_count / total) * 100;
  const flatW = (breadth.flat_count / total) * 100;
  const declineW = (breadth.decline_count / total) * 100;

  return (
    <div style={{ padding: '16px 20px' }}>
      <div style={{ display: 'flex', height: '8px', borderRadius: '4px', overflow: 'hidden', marginBottom: '16px' }}>
        <div style={{ width: `${advanceW}%`, background: 'var(--signal-rise)', opacity: 0.7, transition: 'width 400ms ease-out' }} />
        <div style={{ width: `${flatW}%`, background: 'var(--text-muted)', transition: 'width 400ms ease-out' }} />
        <div style={{ width: `${declineW}%`, background: 'var(--signal-fall)', opacity: 0.7, transition: 'width 400ms ease-out' }} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
        <div className="metric-block">
          <div className="metric-block-value" style={{ color: 'var(--signal-rise)', fontSize: 'var(--fs-lg)' }}>{breadth.advance_count.toLocaleString()}</div>
          <div className="metric-block-label">ADVANCE</div>
        </div>
        <div className="metric-block">
          <div className="metric-block-value" style={{ color: 'var(--signal-fall)', fontSize: 'var(--fs-lg)' }}>{breadth.decline_count.toLocaleString()}</div>
          <div className="metric-block-label">DECLINE</div>
        </div>
        <div className="metric-block">
          <div className="metric-block-value" style={{ fontSize: 'var(--fs-lg)' }}>{breadth.flat_count.toLocaleString()}</div>
          <div className="metric-block-label">FLAT</div>
        </div>
        <div className="metric-block">
          <div className="metric-block-value" style={{ fontSize: 'var(--fs-lg)' }}>{formatAmount(breadth.total_amount)}</div>
          <div className="metric-block-label">TOTAL AMOUNT</div>
        </div>
      </div>
    </div>
  );
}

function SignalList({ stocks }: { stocks: StockQuote[] }) {
  const signals = stocks.slice(0, 12);
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {signals.map((s, i) => {
        const isBuy = s.change_pct > 0;
        return (
          <div key={s.symbol} style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 20px',
            borderBottom: '1px solid rgba(255,255,255,0.03)',
            cursor: 'pointer',
            transition: 'background 80ms ease-out',
          }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'var(--text-muted)', width: '20px', fontVariantNumeric: 'tabular-nums' }}>{String(i + 1).padStart(2, '0')}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent)', width: '72px', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: 'var(--text-primary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
            <span className={`signal-badge ${isBuy ? 'signal-badge--buy' : 'signal-badge--sell'}`}>
              {isBuy ? 'BUY' : 'SELL'}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: priceColor(s.change_pct), fontVariantNumeric: 'tabular-nums', width: '64px', textAlign: 'right' }}>{formatPercent(s.change_pct)}</span>
          </div>
        );
      })}
    </div>
  );
}

function UnusualActivity({ stocks }: { stocks: StockQuote[] }) {
  const unusual = [...stocks]
    .sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0))
    .slice(0, 8);

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {unusual.map((s) => {
        const isSurge = Math.abs(s.change_pct) > 5;
        return (
          <div key={s.symbol} style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 20px',
            borderBottom: '1px solid rgba(255,255,255,0.03)',
            cursor: 'pointer',
            transition: 'background 80ms ease-out',
          }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: priceColor(s.change_pct), fontVariantNumeric: 'tabular-nums', width: '60px', textAlign: 'right', fontWeight: 600 }}>
              {formatPercent(s.change_pct)}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent)', width: '72px', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: 'var(--text-primary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase',
              padding: '2px 8px', borderRadius: '2px',
              background: isSurge ? 'var(--warn-bg)' : 'var(--info-bg)',
              color: isSurge ? 'var(--signal-warn)' : 'var(--signal-info)',
              letterSpacing: '0.08em',
            }}>
              {isSurge ? 'SURGE' : 'ACTIVE'}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function WatchlistPanel({ stocks }: { stocks: StockQuote[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {stocks.slice(0, 10).map((s) => (
        <div key={s.symbol} style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '10px 20px',
          borderBottom: '1px solid rgba(255,255,255,0.03)',
          cursor: 'pointer',
          transition: 'background 80ms ease-out',
        }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent)', width: '72px', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: 'var(--text-primary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: priceColor(s.change_pct), fontVariantNumeric: 'tabular-nums' }}>{formatPrice(s.price)}</span>
        </div>
      ))}
    </div>
  );
}

export function DashboardPage() {
  const [indices, setIndices] = useState<IndexQuote[]>(DEFAULT_INDICES);
  const [breadth, setBreadth] = useState<MarketBreadth | null>(null);
  const [topStocks, setTopStocks] = useState<StockQuote[]>([]);
  const [sectors, setSectors] = useState<SectorData[]>([]);

  useEffect(() => {
    const load = async () => {
      const [ovRes, stockRes, hmRes] = await Promise.allSettled([
        apiGet<Record<string, unknown>>('/market/overview'),
        apiGet<StockQuote[]>('/market/stocks'),
        apiGet<{ items: SectorData[] }>('/market/heatmap'),
      ]);

      if (ovRes.status === 'fulfilled' && ovRes.value) {
        const raw = ovRes.value as Record<string, Record<string, IndexQuote>>;
        const cnIndices = raw.cn_indices ?? {};
        const parsed = Object.entries(cnIndices).map(([code, val]) => ({
          name: val.name ?? code,
          code,
          price: val.price ?? 0,
          change: val.change ?? 0,
          change_pct: val.change_pct ?? 0,
        }));
        if (parsed.length > 0) setIndices(parsed);
        const mb = raw.market_breadth as MarketBreadth | undefined;
        if (mb) setBreadth(mb);
      }

      if (stockRes.status === 'fulfilled' && Array.isArray(stockRes.value)) {
        setTopStocks(stockRes.value);
      }

      if (hmRes.status === 'fulfilled' && hmRes.value?.items) {
        setSectors(hmRes.value.items);
      }
    };
    load();
  }, []);

  return (
    <div style={{ background: '#000000', minHeight: '100%' }}>
      <div style={{
        height: '56px',
        display: 'flex',
        alignItems: 'center',
        background: '#050505',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
      }}>
        {indices.map((idx, i) => (
          <div key={idx.code || i} style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '12px',
            borderRight: i < indices.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
            height: '100%',
            padding: '0 16px',
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', minWidth: '72px' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'var(--text-tertiary)', whiteSpace: 'nowrap', letterSpacing: '0.02em' }}>{idx.name}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '18px', fontWeight: 600, color: priceColor(idx.change_pct), fontVariantNumeric: 'tabular-nums', lineHeight: 1.3 }}>
                {idx.price ? idx.price.toFixed(2) : '—'}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '3px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: priceColor(idx.change_pct), fontVariantNumeric: 'tabular-nums' }}>
                {idx.change_pct ? formatPercent(idx.change_pct) : ''}
              </span>
              <MiniSparkline changePct={idx.change_pct} />
            </div>
          </div>
        ))}
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: '5fr 3fr 3fr',
        gap: '16px',
        padding: '24px',
        minHeight: 'calc(100vh - 56px - 52px)',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={panelStyle}>
            <div style={panelTitleStyle}>板块热力</div>
            <SectorHeatmap sectors={sectors} />
          </div>

          <div style={{ ...panelStyle, flex: 1 }}>
            <div style={panelTitleStyle}>市场广度</div>
            <BreadthBar breadth={breadth} />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ ...panelStyle, flex: 1 }}>
            <div style={panelTitleStyle}>实时信号</div>
            <SignalList stocks={topStocks} />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={panelStyle}>
            <div style={panelTitleStyle}>异动行情</div>
            <UnusualActivity stocks={topStocks} />
          </div>

          <div style={{ ...panelStyle, flex: 1 }}>
            <div style={panelTitleStyle}>自选股</div>
            <WatchlistPanel stocks={topStocks} />
          </div>
        </div>
      </div>
    </div>
  );
}
