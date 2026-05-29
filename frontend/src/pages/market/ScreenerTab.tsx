import { useState, useMemo, useEffect, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiGet } from '@/api/client';
import { EmptyState } from '@/components/ui/EmptyState';
import { formatPrice, formatPercent } from '@/utils/format';
import { LoadingState, changeColor, ACCENT_HEX } from './shared';

interface ScreenerPreset {
  id: string;
  name: string;
  description: string;
  category: string;
  conditions: Array<{
    field: string;
    operator: string;
    value: number | string;
    label: string;
  }>;
}

interface ScreenerResult {
  total: number;
  stocks: Array<{
    symbol: string;
    name: string;
    price: number;
    change_pct: number;
    [key: string]: unknown;
  }>;
}

const CATEGORY_LABELS: Record<string, string> = {
  technical: '技术面',
  fundamental: '基本面',
  quant: '量化',
};

const SCREENER_COLS: Array<{ label: string; key: string; width: string; align: 'left' | 'right' }> = [
  { label: '代码', key: 'symbol', width: '90px', align: 'left' },
  { label: '名称', key: 'name', width: '1fr', align: 'left' },
  { label: '价格', key: 'price', width: '100px', align: 'right' },
  { label: '涨跌幅', key: 'change_pct', width: '100px', align: 'right' },
];

export const ScreenerTab = memo(function ScreenerTab() {
  const navigate = useNavigate();
  const [presets, setPresets] = useState<ScreenerPreset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState<ScreenerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<ScreenerPreset[]>('/screener/presets')
      .then(data => {
        if (cancelled) return;
        setPresets(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setResult(null);
      return;
    }
    let cancelled = false;
    setRunning(true);
    setResult(null);
    apiGet<ScreenerResult>('/screener/run', { preset: selectedId })
      .then(data => {
        if (cancelled) return;
        setResult(data);
        setRunning(false);
      })
      .catch(() => {
        if (cancelled) return;
        setResult(null);
        setRunning(false);
      });
    return () => { cancelled = true; };
  }, [selectedId]);

  const grouped = useMemo(() => {
    const groups: Record<string, ScreenerPreset[]> = {};
    for (const preset of presets) {
      const cat = preset.category || 'other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(preset);
    }
    return groups;
  }, [presets]);

  if (loading) return <LoadingState />;
  if (error || presets.length === 0) return <EmptyState title="暂无选股条件" description="请检查网络连接或稍后重试" size="md" />;

  return (
    <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
      <div style={{
        width: '280px',
        flexShrink: 0,
        borderRight: '1px solid rgba(255,255,255,0.08)',
        overflow: 'auto',
        padding: '12px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}>
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '9px',
              color: 'rgba(255,255,255,0.35)',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              marginBottom: '8px',
              paddingLeft: '4px',
            }}>
              {CATEGORY_LABELS[category] ?? category}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {items.map(preset => (
                <div
                  key={preset.id}
                  onClick={() => setSelectedId(prev => prev === preset.id ? null : preset.id)}
                  style={{
                    padding: '10px 12px',
                    background: selectedId === preset.id ? 'rgba(10,132,255,0.12)' : '#111111',
                    borderRadius: '8px',
                    border: `1px solid ${selectedId === preset.id ? 'rgba(10,132,255,0.3)' : 'rgba(255,255,255,0.06)'}`,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={e => {
                    if (selectedId !== preset.id) {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
                    }
                  }}
                  onMouseLeave={e => {
                    if (selectedId !== preset.id) {
                      e.currentTarget.style.background = '#111111';
                    }
                  }}
                >
                  <div style={{
                    fontFamily: 'var(--font-sans)',
                    fontSize: '13px',
                    fontWeight: 600,
                    color: selectedId === preset.id ? ACCENT_HEX : 'rgba(255,255,255,0.85)',
                    marginBottom: '4px',
                  }}>
                    {preset.name}
                  </div>
                  <div style={{
                    fontFamily: 'var(--font-sans)',
                    fontSize: '11px',
                    color: 'rgba(255,255,255,0.4)',
                    marginBottom: '8px',
                    lineHeight: 1.4,
                  }}>
                    {preset.description}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {preset.conditions.map((cond, idx) => (
                      <span
                        key={idx}
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '9px',
                          color: 'rgba(255,255,255,0.55)',
                          background: 'rgba(255,255,255,0.06)',
                          borderRadius: '4px',
                          padding: '2px 6px',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {cond.label}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {running && <LoadingState />}
        {!running && result && (
          <>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              height: '32px',
              padding: '0 16px',
              flexShrink: 0,
              borderBottom: '1px solid rgba(255,255,255,0.08)',
            }}>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                color: 'rgba(255,255,255,0.35)',
                letterSpacing: '0.06em',
              }}>
                {result.total} 只股票
              </span>
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              height: '32px',
              flexShrink: 0,
              background: '#111111',
              borderBottom: '1px solid rgba(255,255,255,0.08)',
            }}>
              {SCREENER_COLS.map(col => (
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
              {result.stocks.map(stock => (
                <div
                  key={stock.symbol}
                  onClick={() => navigate(`/stock/${stock.symbol}`)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    height: '40px',
                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                    cursor: 'pointer',
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
                  <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                    {formatPrice(stock.price)}
                  </span>
                  <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                    {formatPercent(stock.change_pct)}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
        {!running && !result && selectedId === null && (
          <EmptyState title="请选择选股条件" description="从左侧列表中选择一个条件开始筛选" size="md" />
        )}
        {!running && !result && selectedId !== null && (
          <EmptyState title="暂无选股结果" description="该条件下未筛选到符合条件的股票" size="md" />
        )}
      </div>
    </div>
  );
});
