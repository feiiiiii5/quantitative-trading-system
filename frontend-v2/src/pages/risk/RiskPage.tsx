import { useEffect, useCallback } from 'react';
import { useRiskStore } from '@/stores/risk';
import { useCanvas } from '@/hooks/useCanvas';
import { CorrelationMatrix } from '@/components/charts/CorrelationMatrix';
import { VolatilityCone } from '@/components/charts/VolatilityCone';
import { formatRatio } from '@/utils/format';
import type { RiskLevel } from '@/types';

const FALLBACK_DECOMPOSITION = [
  { source: 'Market', contribution: 0.45 },
  { source: 'Sector', contribution: 0.25 },
  { source: 'Idiosyncratic', contribution: 0.18 },
  { source: 'Liquidity', contribution: 0.12 },
];

const FALLBACK_CORRELATION = {
  labels: ['SH', 'SZ', 'CY', 'HS300', 'ZZ500'],
  values: [
    [1.00, 0.72, 0.65, 0.78, 0.68],
    [0.72, 1.00, 0.81, 0.74, 0.69],
    [0.65, 0.81, 1.00, 0.58, 0.52],
    [0.78, 0.74, 0.58, 1.00, 0.85],
    [0.68, 0.69, 0.52, 0.85, 1.00],
  ],
};

const FALLBACK_VOL_DATES = Array.from({ length: 20 }, (_, i) => {
  const d = new Date(2025, 0, 1 + i * 7);
  return d.toISOString().slice(0, 10);
});

const FALLBACK_HISTORICAL_VOL = [0.22, 0.24, 0.21, 0.26, 0.28, 0.25, 0.23, 0.27, 0.30, 0.29, 0.26, 0.24, 0.22, 0.25, 0.28, 0.31, 0.27, 0.24, 0.23, 0.26];
const FALLBACK_IMPLIED_VOL = [0.25, 0.27, 0.24, 0.29, 0.31, 0.28, 0.26, 0.30, 0.33, 0.32, 0.29, 0.27, 0.25, 0.28, 0.31, 0.34, 0.30, 0.27, 0.26, 0.29];

const PANEL: React.CSSProperties = {
  background: '#0a0a0a',
  borderRadius: '8px',
  border: '1px solid rgba(255,255,255,0.04)',
  boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
  padding: '20px',
};

const PANEL_TITLE: React.CSSProperties = {
  fontFamily: "'Cormorant Garamond', serif",
  fontSize: '18px',
  color: '#C9A96E',
  fontWeight: 500,
  marginBottom: '16px',
};

const LEVEL_COLORS: Record<RiskLevel, { bg: string; color: string }> = {
  LOW: { bg: 'rgba(78,158,110,0.12)', color: '#4E9E6E' },
  MEDIUM: { bg: 'rgba(212,160,74,0.12)', color: '#D4A04A' },
  HIGH: { bg: 'rgba(212,88,74,0.12)', color: '#D4584A' },
  CRITICAL: { bg: 'rgba(212,88,74,0.2)', color: '#D4584A' },
};

function metricColor(value: number, invert = false): string {
  if (invert) {
    if (value < 0) return '#4E9E6E';
    if (value > 0.05) return '#D4584A';
    return '#D4A04A';
  }
  if (value < 0) return '#D4584A';
  if (value > 1) return '#4E9E6E';
  return '#D4A04A';
}

function DecompositionCanvas({ data }: { data: Array<{ source: string; contribution: number }> }) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    if (data.length === 0) return;
    ctx.clearRect(0, 0, w, h);
    const labelWidth = 100;
    const valueWidth = 60;
    const barAreaW = w - labelWidth - valueWidth;
    const barHeight = 20;
    const gap = 12;
    const maxVal = Math.max(...data.map(d => d.contribution), 0.01);

    for (let i = 0; i < data.length; i++) {
      const item = data[i]!;
      const y = i * (barHeight + gap);
      const barW = (item.contribution / maxVal) * barAreaW;

      ctx.fillStyle = '#5E5854';
      ctx.font = '11px JetBrains Mono';
      ctx.textAlign = 'right';
      ctx.fillText(item.source, labelWidth - 8, y + barHeight / 2 + 4);

      const grad = ctx.createLinearGradient(labelWidth, 0, labelWidth + barW, 0);
      grad.addColorStop(0, 'rgba(201,169,110,0.15)');
      grad.addColorStop(1, 'rgba(201,169,110,0.6)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.roundRect(labelWidth, y + 2, barW, barHeight - 4, 3);
      ctx.fill();

      ctx.fillStyle = '#F0EBE3';
      ctx.font = '11px JetBrains Mono';
      ctx.textAlign = 'left';
      ctx.fillText((item.contribution * 100).toFixed(1) + '%', labelWidth + barW + 8, y + barHeight / 2 + 4);
    }
  }, [data]);

  const { ref } = useCanvas(draw, [data]);

  return <canvas ref={ref} style={{ width: '100%', height: Math.max(data.length * 32 + 8, 80) }} />;
}

export function RiskPage() {
  const { var95, cvar, maxDrawdown, sharpe, beta, alerts, metrics, fetchMetrics } = useRiskStore();

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  const decomposition = metrics?.riskDecomposition ?? FALLBACK_DECOMPOSITION;
  const correlation = metrics?.correlationMatrix ?? FALLBACK_CORRELATION;
  const volDates = metrics?.volDates ?? FALLBACK_VOL_DATES;
  const historicalVol = metrics?.historicalVol ?? FALLBACK_HISTORICAL_VOL;
  const impliedVol = metrics?.impliedVol ?? FALLBACK_IMPLIED_VOL;

  const topMetrics: Array<{ label: string; value: string; color: string; subtitle: string }> = [
    { label: 'VaR(95%)', value: formatRatio(var95), color: metricColor(var95), subtitle: 'Value at Risk' },
    { label: 'CVaR', value: formatRatio(cvar), color: metricColor(cvar), subtitle: 'Conditional VaR' },
    { label: 'MAX DRAWDOWN', value: formatRatio(maxDrawdown), color: metricColor(maxDrawdown, true), subtitle: 'Peak to Trough' },
    { label: 'SHARPE', value: sharpe.toFixed(2), color: metricColor(sharpe), subtitle: 'Risk-Adj Return' },
    { label: 'BETA', value: beta.toFixed(2), color: beta > 1 ? '#D4A04A' : '#4E9E6E', subtitle: 'Market Sensitivity' },
  ];

  return (
    <div style={{ minHeight: '100%', background: '#000000', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '12px' }}>
        {topMetrics.map((m) => (
          <div key={m.label} style={{ ...PANEL, padding: '20px' }}>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em', color: '#5E5854', marginBottom: '8px' }}>
              {m.label}
            </div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '24px', fontWeight: 600, color: m.color, fontVariantNumeric: 'tabular-nums', lineHeight: 1.2 }}>
              {m.value}
            </div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '9px', color: '#3A3633', marginTop: '4px' }}>
              {m.subtitle}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
        <div style={PANEL}>
          <div style={PANEL_TITLE}>风险分解</div>
          <DecompositionCanvas data={decomposition} />
        </div>
        <div style={PANEL}>
          <div style={PANEL_TITLE}>相关性矩阵</div>
          <CorrelationMatrix labels={correlation.labels} values={correlation.values} width={400} height={300} />
        </div>
      </div>

      <div style={PANEL}>
        <div style={PANEL_TITLE}>波动率分析</div>
        <VolatilityCone dates={volDates} historical={historicalVol} implied={impliedVol} width={900} height={200} />
      </div>

      <div style={PANEL}>
        <div style={PANEL_TITLE}>风险警报</div>
        {alerts.length === 0 ? (
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '11px', color: '#3A3633', padding: '24px 0', textAlign: 'center', letterSpacing: '0.06em' }}>
            NO ACTIVE ALERTS
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {alerts.map((alert) => {
              const lc = LEVEL_COLORS[alert.level];
              const ts = new Date(alert.timestamp);
              const timeStr = `${ts.getFullYear()}-${String(ts.getMonth() + 1).padStart(2, '0')}-${String(ts.getDate()).padStart(2, '0')} ${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}`;
              return (
                <div key={alert.id} style={{
                  display: 'flex', alignItems: 'center', gap: '12px',
                  padding: '10px 0',
                  borderBottom: '1px solid rgba(255,255,255,0.03)',
                }}>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '10px', color: '#3A3633', fontVariantNumeric: 'tabular-nums', width: '120px', flexShrink: 0 }}>
                    {timeStr}
                  </span>
                  <span style={{
                    fontFamily: "'JetBrains Mono', monospace", fontSize: '9px', textTransform: 'uppercase',
                    letterSpacing: '0.06em', padding: '2px 8px', borderRadius: '2px',
                    background: lc.bg, color: lc.color, flexShrink: 0,
                  }}>
                    {alert.level}
                  </span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '11px', color: '#9B9490', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {alert.message}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
