import { useState, useCallback, memo } from 'react';
import { apiGet } from '@/api/client';
import { formatRatio } from '@/utils/format';
import { ExportButton } from '@/components/ExportButton';

interface RiskAnalysisResult {
  symbols: string[];
  portfolio_var_95: number;
  portfolio_cvar_95: number;
  portfolio_volatility: number;
  portfolio_sharpe: number;
  risk_contribution: Record<string, number>;
}

const METRIC_ROWS = [
  { key: 'portfolio_var_95', label: 'VaR(95%)', format: formatRatio },
  { key: 'portfolio_cvar_95', label: 'CVaR(95%)', format: formatRatio },
  { key: 'portfolio_volatility', label: '年化波动率', format: formatRatio },
  { key: 'portfolio_sharpe', label: 'Sharpe', format: (v: number) => v.toFixed(2) },
] as const;

function compareColor(a: number, b: number, invert = false): string {
  if (a === b) return 'rgba(255,255,255,0.6)';
  const aBetter = invert ? a < b : a > b;
  return aBetter ? '#00C853' : '#FF1744';
}

export const PortfolioComparisonPanel = memo(function PortfolioComparisonPanel() {
  const [groupA, setGroupA] = useState('000001,600036');
  const [groupB, setGroupB] = useState('601318,600519');
  const [dataA, setDataA] = useState<RiskAnalysisResult | null>(null);
  const [dataB, setDataB] = useState<RiskAnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCompare = useCallback(async () => {
    if (!groupA.trim() || !groupB.trim()) {
      setError('请输入两组股票代码');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [resultA, resultB] = await Promise.all([
        apiGet<RiskAnalysisResult>(`/portfolio/risk_analysis?symbols=${encodeURIComponent(groupA)}&period=1y`),
        apiGet<RiskAnalysisResult>(`/portfolio/risk_analysis?symbols=${encodeURIComponent(groupB)}&period=1y`),
      ]);
      setDataA(resultA);
      setDataB(resultB);
    } catch (e) {
      setError(e instanceof Error ? e.message : '对比分析失败');
    } finally {
      setLoading(false);
    }
  }, [groupA, groupB]);

  const exportRows = (() => {
    if (!dataA || !dataB) return [];
    return METRIC_ROWS.map((m) => [
      m.label,
      m.format(dataA[m.key] as number),
      m.format(dataB[m.key] as number),
    ]);
  })();

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <label style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', marginBottom: 4, letterSpacing: '0.06em' }}>
            组合 A（逗号分隔）
          </label>
          <input
            value={groupA}
            onChange={(e) => setGroupA(e.target.value)}
            placeholder="000001,600036"
            style={{
              width: '100%', padding: '8px 12px', fontSize: 12,
              fontFamily: 'var(--font-mono)', background: 'rgba(255,255,255,0.06)',
              border: '1px solid var(--separator)', borderRadius: 'var(--r-xs)',
              color: 'rgba(255,255,255,0.9)', outline: 'none',
            }}
          />
        </div>
        <div style={{ flex: 1 }}>
          <label style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', marginBottom: 4, letterSpacing: '0.06em' }}>
            组合 B（逗号分隔）
          </label>
          <input
            value={groupB}
            onChange={(e) => setGroupB(e.target.value)}
            placeholder="601318,600519"
            style={{
              width: '100%', padding: '8px 12px', fontSize: 12,
              fontFamily: 'var(--font-mono)', background: 'rgba(255,255,255,0.06)',
              border: '1px solid var(--separator)', borderRadius: 'var(--r-xs)',
              color: 'rgba(255,255,255,0.9)', outline: 'none',
            }}
          />
        </div>
        <button
          onClick={handleCompare}
          disabled={loading}
          style={{
            padding: '8px 20px', fontSize: 12, fontWeight: 600,
            fontFamily: 'var(--font-mono)', background: loading ? 'rgba(10,132,255,0.3)' : 'rgba(10,132,255,0.8)',
            border: 'none', borderRadius: 'var(--r-xs)', color: '#fff',
            cursor: loading ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap',
            transition: 'background 0.15s',
          }}
        >
          {loading ? '分析中...' : '对比'}
        </button>
        {dataA && dataB && (
          <ExportButton
            headers={['指标', '组合 A', '组合 B']}
            rows={exportRows}
            filename={`组合对比_${new Date().toISOString().slice(0, 10)}`}
            label="导出"
          />
        )}
      </div>

      {error && (
        <div style={{ padding: '8px 12px', background: 'rgba(255,23,68,0.1)', borderRadius: 'var(--r-xs)', color: '#FF1744', fontSize: 12, fontFamily: 'var(--font-mono)', marginBottom: 12 }}>
          {error}
        </div>
      )}

      {dataA && dataB && (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
            <div style={{ padding: '8px 12px', background: 'rgba(10,132,255,0.08)', borderRadius: 'var(--r-xs)', border: '1px solid rgba(10,132,255,0.15)' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#0A84FF', marginBottom: 4, letterSpacing: '0.06em' }}>组合 A</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {dataA.symbols.map((s) => (
                  <span key={s} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, padding: '2px 8px', borderRadius: 'var(--r-xs)', background: 'rgba(10,132,255,0.12)', color: '#0A84FF' }}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
            <div style={{ padding: '8px 12px', background: 'rgba(255,145,0,0.08)', borderRadius: 'var(--r-xs)', border: '1px solid rgba(255,145,0,0.15)' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#FF9100', marginBottom: 4, letterSpacing: '0.06em' }}>组合 B</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {dataB.symbols.map((s) => (
                  <span key={s} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, padding: '2px 8px', borderRadius: 'var(--r-xs)', background: 'rgba(255,145,0,0.12)', color: '#FF9100' }}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 0, border: '1px solid var(--separator)', borderRadius: 'var(--r-xs)', overflow: 'hidden' }}>
            <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.04)', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', letterSpacing: '0.06em', borderBottom: '1px solid var(--separator)' }}>
              指标
            </div>
            <div style={{ padding: '8px 12px', background: 'rgba(10,132,255,0.06)', fontFamily: 'var(--font-mono)', fontSize: 10, color: '#0A84FF', letterSpacing: '0.06em', borderBottom: '1px solid var(--separator)', textAlign: 'right' }}>
              组合 A
            </div>
            <div style={{ padding: '8px 12px', background: 'rgba(255,145,0,0.06)', fontFamily: 'var(--font-mono)', fontSize: 10, color: '#FF9100', letterSpacing: '0.06em', borderBottom: '1px solid var(--separator)', textAlign: 'right' }}>
              组合 B
            </div>
            {METRIC_ROWS.map((m) => {
              const valA = dataA[m.key] as number;
              const valB = dataB[m.key] as number;
              const invert = m.key === 'portfolio_var_95' || m.key === 'portfolio_cvar_95' || m.key === 'portfolio_volatility';
              return (
                <div key={m.key} style={{ display: 'contents' }}>
                  <div style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.7)', borderBottom: '1px solid var(--separator)' }}>
                    {m.label}
                  </div>
                  <div style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: compareColor(valA, valB, invert), borderBottom: '1px solid var(--separator)', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {m.format(valA)}
                  </div>
                  <div style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: compareColor(valB, valA, invert), borderBottom: '1px solid var(--separator)', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {m.format(valB)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
});
