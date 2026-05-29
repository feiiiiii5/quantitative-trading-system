import { useState, useCallback, useMemo, useEffect, memo } from 'react';
import { apiGet } from '@/api/client';
import { EmptyState } from '@/components/ui/EmptyState';
import { formatAmount, formatPercent } from '@/utils/format';
import { LoadingState, changeColor, ACCENT_HEX } from './shared';
import type { SortDir } from './types';

interface MoneyFlowStock {
  symbol: string;
  name: string;
  main_net_inflow: number;
  main_inflow: number;
  main_outflow: number;
  change_pct: number;
}

type MoneyFlowSortKey = 'symbol' | 'name' | 'main_net_inflow' | 'main_inflow' | 'main_outflow' | 'change_pct';

const MF_COLS: Array<{ label: string; key: MoneyFlowSortKey; width: string; align: 'left' | 'right' }> = [
  { label: '代码', key: 'symbol', width: '90px', align: 'left' },
  { label: '名称', key: 'name', width: '1fr', align: 'left' },
  { label: '主力净流入', key: 'main_net_inflow', width: '120px', align: 'right' },
  { label: '主力流入', key: 'main_inflow', width: '120px', align: 'right' },
  { label: '主力流出', key: 'main_outflow', width: '120px', align: 'right' },
  { label: '涨跌幅', key: 'change_pct', width: '90px', align: 'right' },
];

export const MoneyFlowTab = memo(function MoneyFlowTab() {
  const [stocks, setStocks] = useState<MoneyFlowStock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [sortKey, setSortKey] = useState<MoneyFlowSortKey>('main_net_inflow');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<MoneyFlowStock[]>('/moneyflow/ranking')
      .then(data => {
        if (cancelled) return;
        setStocks(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const handleSort = useCallback((key: MoneyFlowSortKey) => {
    setSortKey(prev => {
      if (prev === key) {
        setSortDir(d => d === 'asc' ? 'desc' : 'asc');
      } else {
        setSortDir('desc');
      }
      return key;
    });
  }, []);

  const sorted = useMemo(() => {
    return [...stocks].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'string' && typeof bv === 'string') {
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [stocks, sortKey, sortDir]);

  if (loading) return <LoadingState />;
  if (error || sorted.length === 0) return <EmptyState title="暂无资金流向数据" description="请检查网络连接或稍后重试" size="md" />;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        height: '32px',
        flexShrink: 0,
        background: '#111111',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        {MF_COLS.map(col => (
          <span
            key={col.key}
            onClick={() => handleSort(col.key)}
            style={{
              width: col.width,
              flexShrink: 0,
              padding: '0 12px',
              fontFamily: 'var(--font-mono)',
              fontSize: '9px',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: sortKey === col.key ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.25)',
              textAlign: col.align,
              cursor: 'pointer',
              userSelect: 'none',
              whiteSpace: 'nowrap',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: col.align === 'right' ? 'flex-end' : 'flex-start',
              boxSizing: 'border-box',
            }}
          >
            {col.label}{sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
          </span>
        ))}
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {sorted.map(stock => (
          <div
            key={stock.symbol}
            style={{
              display: 'flex',
              alignItems: 'center',
              height: '40px',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
              transition: 'background 0.15s ease',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(10,132,255,0.06)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: ACCENT_HEX, fontVariantNumeric: 'tabular-nums' }}>
              {stock.symbol}
            </span>
            <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 500, color: 'rgba(255,255,255,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {stock.name}
            </span>
            <span style={{ width: '120px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(stock.main_net_inflow), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
              {formatAmount(stock.main_net_inflow)}
            </span>
            <span style={{ width: '120px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
              {formatAmount(stock.main_inflow)}
            </span>
            <span style={{ width: '120px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
              {formatAmount(stock.main_outflow)}
            </span>
            <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
              {formatPercent(stock.change_pct)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
});
