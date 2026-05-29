import { useMemo, memo } from 'react';
import type { StockQuote } from '@/types';

interface MarketStatsBarProps {
  stocks: StockQuote[];
}

const LIMIT_UP_PCT = 9.9;
const LIMIT_DOWN_PCT = -9.9;

export const MarketStatsBar = memo(function MarketStatsBar({ stocks }: MarketStatsBarProps) {
  const stats = useMemo(() => {
    let advance = 0;
    let decline = 0;
    let flat = 0;
    let limitUp = 0;
    let limitDown = 0;
    let totalChangePct = 0;
    let totalAmount = 0;

    for (const s of stocks) {
      const pct = s.change_pct ?? 0;
      if (pct > 0) advance++;
      else if (pct < 0) decline++;
      else flat++;
      if (pct >= LIMIT_UP_PCT) limitUp++;
      if (pct <= LIMIT_DOWN_PCT) limitDown++;
      totalChangePct += pct;
      totalAmount += s.amount ?? 0;
    }

    const avgChange = stocks.length > 0 ? totalChangePct / stocks.length : 0;

    return { advance, decline, flat, limitUp, limitDown, avgChange, totalAmount, total: stocks.length };
  }, [stocks]);

  if (stats.total === 0) return null;

  const advPct = ((stats.advance / stats.total) * 100).toFixed(0);
  const decPct = ((stats.decline / stats.total) * 100).toFixed(0);

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      height: '28px',
      padding: '0 var(--s6)',
      background: 'var(--bg-elevated)',
      borderBottom: '1px solid var(--separator-hi)',
      flexShrink: 0,
      gap: 'var(--s6)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--signal-rise)', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{stats.advance}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)' }}>涨</span>
        <div style={{ width: 60, height: 4, borderRadius: 2, background: 'var(--bg-overlay)', overflow: 'hidden', display: 'flex' }}>
          <div style={{ width: `${advPct}%`, background: 'var(--signal-rise)', borderRadius: 2 }} />
          <div style={{ width: `${decPct}%`, background: 'var(--signal-fall)', borderRadius: 2 }} />
        </div>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--signal-fall)', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{stats.decline}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)' }}>跌</span>
      </div>

      <span style={{ width: '1px', height: '12px', background: 'var(--separator)' }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)' }}>均幅</span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontVariantNumeric: 'tabular-nums',
          fontWeight: 600,
          color: stats.avgChange > 0 ? 'var(--signal-rise)' : stats.avgChange < 0 ? 'var(--signal-fall)' : 'var(--label-secondary)',
        }}>
          {stats.avgChange >= 0 ? '+' : ''}{stats.avgChange.toFixed(2)}%
        </span>
      </div>

      {stats.limitUp > 0 && (
        <>
          <span style={{ width: '1px', height: '12px', background: 'var(--separator)' }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)' }}>涨停</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--signal-rise)', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{stats.limitUp}</span>
          </div>
        </>
      )}

      {stats.limitDown > 0 && (
        <>
          <span style={{ width: '1px', height: '12px', background: 'var(--separator)' }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)' }}>跌停</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--signal-fall)', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{stats.limitDown}</span>
          </div>
        </>
      )}

      <span style={{ width: '1px', height: '12px', background: 'var(--separator)' }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)' }}>总额</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums' }}>
          {stats.totalAmount >= 1e12 ? `${(stats.totalAmount / 1e12).toFixed(1)}万亿` : stats.totalAmount >= 1e8 ? `${(stats.totalAmount / 1e8).toFixed(0)}亿` : `${(stats.totalAmount / 1e4).toFixed(0)}万`}
        </span>
      </div>
    </div>
  );
});
