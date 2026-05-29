import { useState, useMemo, useEffect, memo } from 'react';
import { apiGet } from '@/api/client';
import { EmptyState } from '@/components/ui/EmptyState';
import { formatPercent, formatAmount } from '@/utils/format';
import { LoadingState, changeColor, RISE_HEX, FALL_HEX, ACCENT_HEX } from './shared';

interface SectorRotationItem {
  name: string;
  change_pct: number;
  momentum_score: number;
}

interface SectorStrengthItem {
  code: string;
  name: string;
  change_pct: number;
  amount: number;
  turnover_rate: number;
  main_net_inflow: number;
  up_count: number;
  down_count: number;
  leading_stock: string;
  leading_change: number;
  momentum_score: number;
  rank: number;
}

interface SectorMoneyFlow {
  name: string;
  change_pct: number;
  main_net_inflow: number;
  main_inflow: number;
  main_outflow: number;
  code: string;
}

const SR_COLS: Array<{ label: string; key: string; width: string; align: 'left' | 'right' }> = [
  { label: '板块', key: 'name', width: '1fr', align: 'left' },
  { label: '涨跌幅', key: 'change_pct', width: '120px', align: 'right' },
  { label: '动量分数', key: 'momentum_score', width: '140px', align: 'right' },
];

export const SectorRotationTab = memo(function SectorRotationTab() {
  const [rotation, setRotation] = useState<SectorRotationItem[]>([]);
  const [strength, setStrength] = useState<SectorStrengthItem[]>([]);
  const [moneyFlow, setMoneyFlow] = useState<SectorMoneyFlow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);

    const withTimeout = <T,>(p: Promise<T>, ms: number): Promise<T | null> =>
      Promise.race([p, new Promise<null>((_, reject) => setTimeout(() => reject(new Error('timeout')), ms))]);

    Promise.all([
      withTimeout(apiGet<{
        snapshot: {
          top_sectors: Array<{ name: string; change_pct: number; momentum_score: number }>;
          bottom_sectors: Array<{ name: string; change_pct: number; momentum_score: number }>;
        };
        trend: unknown[];
        signals: unknown[];
      }>('/sector/rotation'), 10000).catch(() => null),
      withTimeout(apiGet<SectorStrengthItem[]>('/sector/strength'), 10000).catch(() => null),
      withTimeout(apiGet<SectorMoneyFlow[]>('/moneyflow/sector'), 10000).catch(() => null),
    ])
      .then(([rotData, strData, mfData]) => {
        if (cancelled) return;
        const top = rotData?.snapshot?.top_sectors ?? [];
        const bottom = rotData?.snapshot?.bottom_sectors ?? [];
        setRotation([...top, ...bottom]);
        setStrength(Array.isArray(strData) ? strData : []);
        setMoneyFlow(Array.isArray(mfData) ? mfData : []);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  const sortedMoneyFlow = useMemo(() => {
    return [...moneyFlow].sort((a, b) => b.main_net_inflow - a.main_net_inflow);
  }, [moneyFlow]);

  if (loading) return <LoadingState />;
  if (error || (rotation.length === 0 && strength.length === 0 && moneyFlow.length === 0)) return <EmptyState title="暂无行情数据" description="请检查网络连接或稍后重试" size="lg" />;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'auto' }}>
      {strength.length > 0 && (
        <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '9px',
            color: 'rgba(255,255,255,0.35)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            marginBottom: '12px',
          }}>
            板块强度排行
          </div>
          <div style={{ display: 'flex', gap: '10px', overflowX: 'auto', paddingBottom: '4px' }}>
            {strength
              .sort((a, b) => b.momentum_score - a.momentum_score)
              .map(item => {
                const trend: 'up' | 'down' = item.change_pct >= 0 ? 'up' : 'down';
                return (
                <div
                  key={item.name}
                  style={{
                    flexShrink: 0,
                    width: '140px',
                    padding: '12px',
                    background: '#111111',
                    borderRadius: '8px',
                    border: '1px solid rgba(255,255,255,0.06)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>
                      {item.name}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '11px',
                      color: trend === 'up' ? RISE_HEX : FALL_HEX,
                    }}>
                      {trend === 'up' ? '↑' : '↓'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <div style={{
                      flex: 1,
                      height: '4px',
                      background: 'rgba(255,255,255,0.06)',
                      borderRadius: '2px',
                      overflow: 'hidden',
                    }}>
                      <div style={{
                        width: `${Math.min(Math.max(item.momentum_score, 0), 100)}%`,
                        height: '100%',
                        background: item.momentum_score >= 70 ? RISE_HEX : item.momentum_score >= 40 ? ACCENT_HEX : FALL_HEX,
                        borderRadius: '2px',
                      }} />
                    </div>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.6)', fontVariantNumeric: 'tabular-nums', minWidth: '24px', textAlign: 'right' }}>
                      {item.momentum_score}
                    </span>
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: ACCENT_HEX, fontVariantNumeric: 'tabular-nums' }}>
                    {item.leading_stock}
                  </span>
                </div>
              );})
              }
          </div>
        </div>
      )}

      {moneyFlow.length > 0 && (
        <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '9px',
            color: 'rgba(255,255,255,0.35)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            marginBottom: '12px',
          }}>
            板块资金流
          </div>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            height: '32px',
            flexShrink: 0,
            background: '#111111',
            borderBottom: '1px solid rgba(255,255,255,0.08)',
          }}>
            <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', whiteSpace: 'nowrap' }}>板块名称</span>
            <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', textAlign: 'right', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', boxSizing: 'border-box' }}>涨跌幅</span>
            <span style={{ width: '130px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', textAlign: 'right', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', boxSizing: 'border-box' }}>主力净流入</span>
            <span style={{ width: '130px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', textAlign: 'right', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', boxSizing: 'border-box' }}>主力流入</span>
            <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', textAlign: 'right', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', boxSizing: 'border-box' }}>主力流出</span>
          </div>
          {sortedMoneyFlow.map(sector => (
            <div
              key={sector.code}
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
              <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 500, color: 'rgba(255,255,255,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {sector.name}
              </span>
              <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(sector.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                {formatPercent(sector.change_pct)}
              </span>
              <span style={{ width: '130px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: sector.main_net_inflow >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                {formatAmount(sector.main_net_inflow)}
              </span>
              <span style={{ width: '130px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
                {formatAmount(sector.main_inflow)}
              </span>
              <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
                {formatAmount(sector.main_outflow)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          height: '32px',
          flexShrink: 0,
          background: '#111111',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}>
          {SR_COLS.map(col => (
            <span
              key={col.key}
              style={{
                width: col.width,
                flexShrink: 0,
                padding: '0 12px',
                fontFamily: 'var(--font-mono)',
                fontSize: '9px',
                textTransform: 'uppercase',
                letterSpacing: '0.1em',
                color: 'rgba(255,255,255,0.25)',
                textAlign: col.align,
                whiteSpace: 'nowrap',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: col.align === 'right' ? 'flex-end' : 'flex-start',
                boxSizing: 'border-box',
              }}
            >
              {col.label}
            </span>
          ))}
        </div>
        <div style={{ flex: 1, overflow: 'auto' }}>
          {rotation.map(sector => (
            <div
                key={sector.name}
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
                <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 500, color: 'rgba(255,255,255,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {sector.name}
                </span>
                <span style={{ width: '120px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(sector.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                  {formatPercent(sector.change_pct)}
                </span>
                <span style={{ width: '140px', flexShrink: 0, padding: '0 12px', display: 'flex', alignItems: 'center', gap: '8px', boxSizing: 'border-box' }}>
                  <div style={{
                    flex: 1,
                    height: '4px',
                    background: 'rgba(255,255,255,0.06)',
                    borderRadius: '2px',
                    overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${Math.min(Math.max(sector.momentum_score, 0), 100)}%`,
                      height: '100%',
                      background: sector.momentum_score >= 70 ? RISE_HEX : sector.momentum_score >= 40 ? ACCENT_HEX : FALL_HEX,
                      borderRadius: '2px',
                    }} />
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'rgba(255,255,255,0.5)', fontVariantNumeric: 'tabular-nums', minWidth: '28px', textAlign: 'right' }}>
                    {sector.momentum_score.toFixed(0)}
                  </span>
                </span>
              </div>
            ))}
          </div>
      </div>
    </div>
  );
});
