import { useEffect, useState, useCallback, memo } from 'react';
import { apiPost } from '@/api/client';
import { useMarketStore } from '@/stores/market';
import { useRiskStore } from '@/stores/risk';
import { useWatchlistStore } from '@/stores/watchlist';
import { Sparkline } from '@/components/charts/Sparkline';
import { HeatmapCanvas } from '@/components/charts/HeatmapCanvas';
import { RiskBanner } from '@/components/ui/RiskBanner';
import { SignalBadge } from '@/components/ui/SignalBadge';
import { formatPrice, formatPercent, formatAmount, priceColor } from '@/utils/format';
import type { StockQuote, IndexQuote, SignalItem } from '@/types';

const DEFAULT_INDICES: IndexQuote[] = [
  { name: '上证指数', code: 'sh000001', price: 0, change: 0, change_pct: 0 },
  { name: '深证成指', code: 'sz399001', price: 0, change: 0, change_pct: 0 },
  { name: '创业板指', code: 'sz399006', price: 0, change: 0, change_pct: 0 },
  { name: '沪深300', code: 'sh000300', price: 0, change: 0, change_pct: 0 },
  { name: '中证500', code: 'sh000905', price: 0, change: 0, change_pct: 0 },
  { name: '科创50', code: 'sh000688', price: 0, change: 0, change_pct: 0 },
];

const MONO = "'JetBrains Mono', monospace";
const SERIF = "'Cormorant Garamond', serif";
const SANS = 'system-ui, -apple-system, sans-serif';

const PANEL: React.CSSProperties = {
  background: '#0a0a0a',
  borderRadius: '8px',
  border: '1px solid rgba(255,255,255,0.04)',
  boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
  overflow: 'hidden',
};

const PANEL_TITLE: React.CSSProperties = {
  fontFamily: SERIF,
  fontSize: '18px',
  color: '#C9A96E',
  fontWeight: 500,
  padding: '16px 20px',
  borderBottom: '1px solid rgba(255,255,255,0.04)',
};

const HeroTickerBar = memo(function HeroTickerBar({ indices }: { indices: IndexQuote[] }) {
  return (
    <div style={{
      height: '64px',
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
            <span style={{ fontFamily: SANS, fontSize: '10px', color: '#5E5854', whiteSpace: 'nowrap', letterSpacing: '0.02em' }}>
              {idx.name}
            </span>
            <span style={{ fontFamily: MONO, fontSize: '18px', fontWeight: 600, color: priceColor(idx.change_pct), fontVariantNumeric: 'tabular-nums', lineHeight: 1.3 }}>
              {idx.price ? idx.price.toFixed(2) : '—'}
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '3px' }}>
            <span style={{ fontFamily: MONO, fontSize: '10px', color: priceColor(idx.change_pct), fontVariantNumeric: 'tabular-nums' }}>
              {idx.change_pct ? formatPercent(idx.change_pct) : ''}
            </span>
            <Sparkline
              data={Array.from({ length: 16 }, (_, j) => {
                const t = j / 15;
                const trend = idx.change_pct > 0 ? 0.4 * t : idx.change_pct < 0 ? -0.4 * t : 0;
                return trend + Math.sin(j * 1.8 + idx.change_pct * 8) * 0.25 + Math.sin(j * 3.1 + idx.change_pct * 4) * 0.12;
              })}
              width={50}
              height={14}
              color={idx.change_pct >= 0 ? '#D4584A' : '#4E9E6E'}
            />
          </div>
        </div>
      ))}
    </div>
  );
});

const BreadthBar = memo(function BreadthBar({ breadth }: { breadth: { advance_count: number; decline_count: number; flat_count: number; total_amount: number } | null }) {
  if (!breadth) return null;
  const total = breadth.advance_count + breadth.decline_count + breadth.flat_count;
  if (total === 0) return null;
  const advanceW = (breadth.advance_count / total) * 100;
  const flatW = (breadth.flat_count / total) * 100;
  const declineW = (breadth.decline_count / total) * 100;

  return (
    <div style={{ padding: '16px 20px' }}>
      <div style={{ display: 'flex', height: '8px', borderRadius: '4px', overflow: 'hidden', marginBottom: '16px' }}>
        <div style={{ width: `${advanceW}%`, background: '#D4584A', opacity: 0.7, transition: 'width 400ms ease-out' }} />
        <div style={{ width: `${flatW}%`, background: '#3A3633', transition: 'width 400ms ease-out' }} />
        <div style={{ width: `${declineW}%`, background: '#4E9E6E', opacity: 0.7, transition: 'width 400ms ease-out' }} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
        {[
          { label: 'ADVANCE', value: breadth.advance_count.toLocaleString(), color: '#D4584A' },
          { label: 'DECLINE', value: breadth.decline_count.toLocaleString(), color: '#4E9E6E' },
          { label: 'FLAT', value: breadth.flat_count.toLocaleString(), color: '#F0EBE3' },
          { label: 'TOTAL AMOUNT', value: formatAmount(breadth.total_amount), color: '#F0EBE3' },
        ].map(m => (
          <div key={m.label} style={{ textAlign: 'center' }}>
            <div style={{ fontFamily: MONO, fontSize: '18px', color: m.color, fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{m.value}</div>
            <div style={{ fontFamily: MONO, fontSize: '9px', color: '#3A3633', letterSpacing: '0.08em', marginTop: '4px' }}>{m.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
});

const SignalList = memo(function SignalList({ signals }: { signals: SignalItem[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {signals.slice(0, 12).map((s, i) => (
        <div key={`${s.symbol}-${i}`} style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '10px 20px',
          borderBottom: '1px solid rgba(255,255,255,0.03)',
          cursor: 'pointer',
          transition: 'background 80ms ease-out',
        }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
        >
          <span style={{ fontFamily: MONO, fontSize: '9px', color: '#3A3633', width: '20px', fontVariantNumeric: 'tabular-nums' }}>
            {String(i + 1).padStart(2, '0')}
          </span>
          <span style={{ fontFamily: MONO, fontSize: '11px', color: '#C9A96E', width: '72px', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
          <span style={{ fontFamily: SANS, fontSize: '12px', color: '#F0EBE3', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
          <SignalBadge action={s.action} />
          <span style={{ fontFamily: MONO, fontSize: '11px', color: priceColor(s.change_pct), fontVariantNumeric: 'tabular-nums', width: '64px', textAlign: 'right' }}>
            {formatPercent(s.change_pct)}
          </span>
        </div>
      ))}
    </div>
  );
});

const UnusualActivity = memo(function UnusualActivity({ stocks }: { stocks: StockQuote[] }) {
  const unusual = [...stocks].sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0)).slice(0, 8);

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {unusual.map(s => {
        const isSurge = Math.abs(s.change_pct) > 5;
        return (
          <div key={s.symbol} style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 20px',
            borderBottom: '1px solid rgba(255,255,255,0.03)',
            cursor: 'pointer',
            transition: 'background 80ms ease-out',
          }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{ fontFamily: MONO, fontSize: '13px', color: priceColor(s.change_pct), fontVariantNumeric: 'tabular-nums', width: '60px', textAlign: 'right', fontWeight: 600 }}>
              {formatPercent(s.change_pct)}
            </span>
            <span style={{ fontFamily: MONO, fontSize: '11px', color: '#C9A96E', width: '72px', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
            <span style={{ fontFamily: SANS, fontSize: '12px', color: '#F0EBE3', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
            <span style={{
              fontFamily: MONO, fontSize: '9px', textTransform: 'uppercase',
              padding: '2px 8px', borderRadius: '2px',
              background: isSurge ? 'rgba(212,160,74,0.06)' : 'rgba(107,143,181,0.06)',
              color: isSurge ? '#D4A04A' : '#6B8FB5',
              letterSpacing: '0.08em',
            }}>
              {isSurge ? 'SURGE' : 'ACTIVE'}
            </span>
          </div>
        );
      })}
    </div>
  );
});

const WatchlistPanel = memo(function WatchlistPanel({ stocks }: { stocks: StockQuote[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {stocks.length === 0 ? (
        <div style={{ padding: '32px 20px', textAlign: 'center', fontFamily: MONO, fontSize: '11px', color: '#3A3633', letterSpacing: '0.06em' }}>
          NO WATCHLIST ITEMS
        </div>
      ) : (
        stocks.slice(0, 10).map(s => (
          <div key={s.symbol} style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 20px',
            borderBottom: '1px solid rgba(255,255,255,0.03)',
            cursor: 'pointer',
            transition: 'background 80ms ease-out',
          }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{ fontFamily: MONO, fontSize: '11px', color: '#C9A96E', width: '72px', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
            <span style={{ fontFamily: SANS, fontSize: '12px', color: '#F0EBE3', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
            <span style={{ fontFamily: MONO, fontSize: '12px', color: priceColor(s.change_pct), fontVariantNumeric: 'tabular-nums' }}>{formatPrice(s.price)}</span>
          </div>
        ))
      )}
    </div>
  );
});

const AISummaryCard = memo(function AISummaryCard() {
  const [expanded, setExpanded] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchSummary = useCallback(async () => {
    if (summary) return;
    setLoading(true);
    try {
      const data = await apiPost<{ summary: string }>('/ai/summary');
      setSummary(data?.summary ?? 'AI摘要暂不可用');
    } catch {
      setSummary('AI摘要服务暂不可用，请稍后再试');
    }
    setLoading(false);
  }, [summary]);

  const handleToggle = useCallback(() => {
    if (!expanded) fetchSummary();
    setExpanded(v => !v);
  }, [expanded, fetchSummary]);

  return (
    <div style={{
      ...PANEL,
      transition: 'height 280ms cubic-bezier(0.16,1,0.3,1)',
      height: expanded ? '300px' : '48px',
      overflow: 'hidden',
    }}>
      <div
        onClick={handleToggle}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 20px', height: '48px', cursor: 'pointer',
          borderBottom: expanded ? '1px solid rgba(255,255,255,0.04)' : 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontFamily: SERIF, fontSize: '16px', color: '#C9A96E', fontWeight: 500 }}>AI 市场摘要</span>
          <span style={{
            fontFamily: MONO, fontSize: '8px', padding: '1px 6px', borderRadius: '2px',
            background: 'rgba(155,125,184,0.12)', color: '#9B7DB8', letterSpacing: '0.06em',
          }}>
            LLM
          </span>
        </div>
        <span style={{ fontFamily: MONO, fontSize: '10px', color: '#5E5854', transition: 'transform 280ms ease-out', display: 'inline-block', transform: expanded ? 'rotate(180deg)' : 'rotate(0)' }}>
          ▼
        </span>
      </div>
      <div style={{ padding: '20px', overflow: 'auto', height: 'calc(300px - 48px)' }}>
        {loading ? (
          <div style={{ fontFamily: MONO, fontSize: '11px', color: '#5E5854', letterSpacing: '0.06em' }}>GENERATING SUMMARY...</div>
        ) : (
          <div style={{ fontFamily: SANS, fontSize: '13px', color: '#9B9490', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
            {summary ?? ''}
          </div>
        )}
      </div>
    </div>
  );
});

export function DashboardPage() {
  const { indices, stocks, sectors, breadth, fetchIndices, fetchStocks, fetchSectors } = useMarketStore();
  const { riskLevel, maxDrawdown, alerts } = useRiskStore();
  const watchlistSymbols = useWatchlistStore(s => s.symbols);
  const [displayIndices, setDisplayIndices] = useState<IndexQuote[]>(DEFAULT_INDICES);
  const [signals, setSignals] = useState<SignalItem[]>([]);

  useEffect(() => {
    const load = async () => {
      await Promise.allSettled([fetchIndices(), fetchStocks(), fetchSectors()]);
    };
    load();
  }, [fetchIndices, fetchStocks, fetchSectors]);

  useEffect(() => {
    if (indices.length > 0) setDisplayIndices(indices);
  }, [indices]);

  useEffect(() => {
    if (stocks.length > 0) {
      const sigs: SignalItem[] = stocks.slice(0, 12).map(s => ({
        symbol: s.symbol,
        name: s.name,
        action: s.change_pct > 1 ? 'BUY' : s.change_pct < -1 ? 'SELL' : 'HOLD' as const,
        change_pct: s.change_pct,
        confidence: Math.min(Math.abs(s.change_pct) * 20, 100),
      }));
      setSignals(sigs);
    }
  }, [stocks]);

  const watchlistStocks = stocks.filter(s => watchlistSymbols.includes(s.symbol));

  return (
    <div style={{ background: '#000000', minHeight: '100%' }}>
      <HeroTickerBar indices={displayIndices} />

      <RiskBanner
        level={riskLevel}
        maxDrawdown={maxDrawdown}
        alertCount={alerts.length}
      />

      <div style={{
        display: 'grid',
        gridTemplateColumns: '5fr 3fr 3fr',
        gap: '16px',
        padding: '24px',
        minHeight: 'calc(100vh - 64px - 52px - 40px)',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={PANEL}>
            <div style={PANEL_TITLE}>板块热力</div>
            <div style={{ padding: '16px 20px' }}>
              <HeatmapCanvas sectors={sectors} width={500} height={240} />
            </div>
          </div>
          <div style={{ ...PANEL, flex: 1 }}>
            <div style={PANEL_TITLE}>市场广度</div>
            <BreadthBar breadth={breadth} />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ ...PANEL, flex: 1 }}>
            <div style={PANEL_TITLE}>实时信号</div>
            <SignalList signals={signals} />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={PANEL}>
            <div style={PANEL_TITLE}>异动行情</div>
            <UnusualActivity stocks={stocks} />
          </div>
          <div style={{ ...PANEL, flex: 1 }}>
            <div style={PANEL_TITLE}>自选股</div>
            <WatchlistPanel stocks={watchlistStocks} />
          </div>
        </div>
      </div>

      <div style={{ padding: '0 24px 24px' }}>
        <AISummaryCard />
      </div>
    </div>
  );
}
