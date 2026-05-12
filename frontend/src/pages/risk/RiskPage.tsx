import { useEffect, useCallback, memo, useState, useMemo } from 'react';
import { useRiskStore } from '@/stores/risk';
import { useCanvas } from '@/hooks/useCanvas';
import { CorrelationMatrix } from '@/components/charts/CorrelationMatrix';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { VolatilityCone } from '@/components/charts/VolatilityCone';
import { EmptyState } from '@/components/ui/EmptyState';
import { formatRatio } from '@/utils/format';
import { apiGet } from '@/api/client';
import type { RiskLevel, RiskMetrics } from '@/types';
import { usePortfolioRiskDashboard, useStressScenarios } from '@/hooks/queries/usePortfolioQueries';
import { useRiskPortfolio, useRiskExposure, useDrawdownAnalysis, useEfficientFrontier, useMonteCarloVaR, useCorrelationMatrix, useBlackLitterman, useKellyCalculator, useRunStressTest } from '@/hooks/queries/useRiskQueries';

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

const LEVEL_COLORS: Record<RiskLevel, { bg: string; color: string }> = {
  LOW: { bg: 'rgba(0,200,83,0.15)', color: '#00C853' },
  MEDIUM: { bg: 'rgba(255,145,0,0.15)', color: '#FF9100' },
  HIGH: { bg: 'rgba(255,23,68,0.15)', color: '#FF1744' },
  CRITICAL: { bg: 'rgba(255,23,68,0.22)', color: '#FF1744' },
};


type BorderColor = '#FF1744' | '#FF9100' | '#00C853';

function varBorderColor(value: number): BorderColor {
  if (value > 0.05) return '#FF1744';
  if (value > 0.02) return '#FF9100';
  return '#00C853';
}

function sharpeBorderColor(value: number): BorderColor {
  if (value > 1) return '#00C853';
  if (value >= 0.5) return '#FF9100';
  return '#FF1744';
}

function betaBorderColor(value: number): BorderColor {
  if (value > 1) return '#FF9100';
  return '#00C853';
}

function metricColor(value: number, invert = false): string {
  if (invert) {
    if (value < 0) return '#00C853';
    if (value > 0.05) return '#FF1744';
    return '#FF9100';
  }
  if (value < 0) return '#FF1744';
  if (value > 1) return '#00C853';
  return '#FF9100';
}

function isDataLoading(var95: number, cvar: number, maxDrawdown: number, sharpe: number, beta: number): boolean {
  return var95 === 0 && cvar === 0 && maxDrawdown === 0 && sharpe === 0 && beta === 0;
}

interface PortfolioData {
  var_95: number;
  cvar_95: number;
  beta: number;
  symbols: string[];
  position_count: number;
  annualized_vol: number;
}

interface ExposureData {
  sectors: Record<string, number>;
  concentration: number;
  position_count: number;
  diversification_score: number;
}

interface DrawdownEpisode {
  start_idx: number;
  trough_idx: number;
  end_idx: number;
  depth: number;
  duration_bars: number;
  recovery_bars: number;
  recovered: boolean;
}

interface DrawdownData {
  symbol: string;
  period: string;
  episodes: DrawdownEpisode[];
  avg_recovery_bars: number;
  recovery_rate: number;
  total_episodes: number;
}

interface FrontierPoint {
  return: number;
  volatility: number;
  sharpe_ratio: number;
  weights: Record<string, number>;
}

interface EfficientFrontierData {
  symbols: string[];
  period: string;
  risk_free_rate: number;
  frontier: FrontierPoint[];
  optimal_portfolios: {
    min_variance: FrontierPoint;
    max_sharpe: FrontierPoint;
  };
}

interface MonteCarloVaRData {
  var_95: number;
  var_99: number;
  cvar_95: number;
  cvar_99: number;
  mean_portfolio_return: number;
  std_portfolio_return: number;
  n_simulations: number;
  confidence_levels: Record<string, number>;
  method: string;
  message: string;
}

interface CorrelationMatrixData {
  symbols: string[];
  period: string;
  full_correlation: Record<string, Record<string, number>>;
  rolling_correlation: Record<string, Record<string, number>>;
  rolling_window: number;
}

interface BlackLittermanData {
  posterior_returns: Record<string, number>;
  weights: Record<string, number>;
  expected_return: number;
  expected_volatility: number;
  sharpe_ratio: number;
  message: string;
}

interface KellyData {
  kelly_full: number;
  suggested_fraction: number;
  fraction_type: string;
  win_rate: number;
  win_loss_ratio: number;
  expected_value: number;
  ruin_probability: number;
  max_position_pct: number;
}

interface StressScenario {
  name: string;
  description: string;
  equity_shock: number;
  bond_shock: number;
  commodity_shock: number;
  volatility_mult: number;
}

interface StressTestResult {
  scenarios: Array<{
    name: string;
    portfolio_impact: number;
    portfolio_volatility: number;
    max_drawdown: number;
    recovery_days: number;
  }>;
  summary: {
    worst_case: number;
    average_impact: number;
    stress_score: number;
  };
}

interface DiversificationData {
  diversification_score: number;
  avg_correlation: number;
  concentration_risk: number;
  suggested_assets: string[];
}

interface AttributionData {
  symbols: string[];
  weights: Record<string, number>;
  returns: Record<string, number>;
  contribution: Record<string, number>;
  sector: Record<string, string>;
}

const pulseKeyframes = `
@keyframes riskPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
@keyframes subtleBreathe {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}
@keyframes dotPulse {
  0%, 100% { transform: scale(1); opacity: 0.7; }
  50% { transform: scale(1.3); opacity: 1; }
}
`;

const DecompositionCanvas = memo(function DecompositionCanvas({ data }: { data: Array<{ source: string; contribution: number }> }) {
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

      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.font = '11px SF Mono, JetBrains Mono, monospace';
      ctx.textAlign = 'right';
      ctx.fillText(item.source, labelWidth - 8, y + barHeight / 2 + 4);

      const grad = ctx.createLinearGradient(labelWidth, 0, labelWidth + barW, 0);
      grad.addColorStop(0, 'rgba(10,132,255,0.18)');
      grad.addColorStop(1, 'rgba(10,132,255,0.6)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.roundRect(labelWidth, y + 2, barW, barHeight - 4, 3);
      ctx.fill();

      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.font = '11px SF Mono, JetBrains Mono, monospace';
      ctx.textAlign = 'left';
      ctx.fillText((item.contribution * 100).toFixed(1) + '%', labelWidth + barW + 8, y + barHeight / 2 + 4);
    }
  }, [data]);

  const { ref } = useCanvas(draw, [data]);

  return <canvas ref={ref} style={{ width: '100%', height: Math.max(data.length * 32 + 8, 80) }} />;
});

const GaugeCard = memo(function GaugeCard({ value, max, label, unit }: {
  value: number; max: number; label: string; unit: string;
}) {
  const ratio = Math.min(Math.abs(value) / max, 1);
  const radius = 40;
  const circumference = Math.PI * radius;
  const offset = circumference * (1 - ratio);
  const color = ratio < 0.4 ? 'var(--green)' : ratio < 0.7 ? 'var(--orange)' : 'var(--red)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <svg width={100} height={55} viewBox="0 0 100 55">
        <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="var(--border-default)" strokeWidth={6} strokeLinecap="round" />
        <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke={color} strokeWidth={6} strokeLinecap="round"
          strokeDasharray={circumference} strokeDashoffset={offset} style={{ transition: 'stroke-dashoffset 0.6s var(--ease-apple)' }} />
      </svg>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 600, color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>
        {value.toFixed(2)}{unit}
      </span>
      <span style={{ fontSize: 10, color: 'var(--label-tertiary)', fontFamily: 'var(--font-mono)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</span>
    </div>
  );
});

const MetricCard = memo(function MetricCard({
  label,
  value,
  color,
  subtitle,
  borderColor,
  isLoading,
}: {
  label: string;
  value: string;
  color: string;
  subtitle: string;
  borderColor: BorderColor;
  isLoading: boolean;
}) {
  return (
    <div style={{
      background: 'var(--bg-glass)',
      backdropFilter: 'blur(24px) saturate(120%)',
      borderRadius: 'var(--r-lg)',
      border: '1px solid var(--separator)',
      borderLeft: `4px solid ${borderColor}`,
      padding: '24px 20px',
      transition: 'transform var(--dur-fast) var(--ease-apple), box-shadow var(--dur-fast) var(--ease-apple)',
      position: 'relative',
      overflow: 'hidden',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase',
        letterSpacing: '0.08em', color: 'var(--label-tertiary)', marginBottom: 10,
      }}>
        {label}
      </div>
      {isLoading ? (
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 28, fontWeight: 700,
          color: 'var(--label-quaternary)', fontVariantNumeric: 'tabular-nums', lineHeight: 1.2,
          animation: 'subtleBreathe 2s ease-in-out infinite',
        }}>
          --
        </div>
      ) : (
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 28, fontWeight: 700,
          color, fontVariantNumeric: 'tabular-nums', lineHeight: 1.2,
        }}>
          {value}
        </div>
      )}
      <div style={{
        fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--label-tertiary)',
        marginTop: 6,
      }}>
        {subtitle}
      </div>
    </div>
  );
});

const CorrelationLegend = memo(function CorrelationLegend() {
  const stops = 11;
  const items = Array.from({ length: stops }, (_, i) => {
    const v = -1 + (2 * i) / (stops - 1);
    let r: number, g: number, b: number;
    if (v >= 0) {
      r = Math.round(255 * Math.abs(v));
      g = Math.round(23 * (1 - Math.abs(v) * 0.6));
      b = Math.round(68 * (1 - Math.abs(v) * 0.6));
    } else {
      r = Math.round(10 * (1 - Math.abs(v) * 0.3));
      g = Math.round(132 * (0.5 + Math.abs(v) * 0.5));
      b = Math.round(255 * (0.5 + Math.abs(v) * 0.5));
    }
    return { v, color: `rgb(${r},${g},${b})` };
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)' }}>-1.0</span>
      <div style={{ display: 'flex', height: 10, borderRadius: 2, overflow: 'hidden', flex: 1, maxWidth: 200 }}>
        {items.map((item, idx) => (
          <div key={idx} style={{ flex: 1, background: item.color }} />
        ))}
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)' }}>+1.0</span>
      <span style={{ fontFamily: 'var(--font-sans)', fontSize: 9, color: 'var(--label-quaternary)', marginLeft: 4 }}>
        负相关 ← → 正相关
      </span>
    </div>
  );
});

const AlertTimeline = memo(function AlertTimeline({ alerts }: { alerts: Array<{ id: string; level: RiskLevel; message: string; value: number; timestamp: number }> }) {
  if (alerts.length === 0) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        padding: '48px 0', gap: 12,
      }}>
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#00C853" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: '#00C853', letterSpacing: '0.04em', fontWeight: 500 }}>
          无活跃风险警报
        </span>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--label-quaternary)' }}>
          所有风险指标均在安全范围内
        </span>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {alerts.map((alert) => {
        const lc = LEVEL_COLORS[alert.level];
        const ts = new Date(alert.timestamp);
        const timeStr = `${ts.getFullYear()}-${String(ts.getMonth() + 1).padStart(2, '0')}-${String(ts.getDate()).padStart(2, '0')} ${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}`;
        const isCritical = alert.level === 'CRITICAL';
        return (
          <div key={alert.id} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '12px 0',
            borderBottom: '1px solid var(--separator)',
          }}>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-quaternary)',
              fontVariantNumeric: 'tabular-nums', width: 120, flexShrink: 0,
            }}>
              {timeStr}
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
              letterSpacing: '0.06em', padding: '3px 10px', borderRadius: 'var(--r-xs)',
              background: lc.bg, color: lc.color, flexShrink: 0,
              animation: isCritical ? 'riskPulse 1.5s ease-in-out infinite' : 'none',
            }}>
              {alert.level}
            </span>
            <span style={{
              fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--label-secondary)',
              flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {alert.message}
            </span>
          </div>
        );
      })}
    </div>
  );
});

const RiskLevelBadge = memo(function RiskLevelBadge({ level, isLoading }: { level: RiskLevel; isLoading: boolean }) {
  const lc = LEVEL_COLORS[level];
  const isCritical = level === 'CRITICAL';
  const displayLevel = isLoading ? 'INIT' : level;

  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 10,
      padding: '8px 20px', borderRadius: 'var(--r-lg)',
      background: lc.bg, border: `1px solid ${lc.color}33`,
    }}>
      <div style={{
        width: 8, height: 8, borderRadius: '50%',
        background: lc.color,
        animation: isCritical ? 'dotPulse 1s ease-in-out infinite' : (isLoading ? 'subtleBreathe 2s ease-in-out infinite' : 'none'),
      }} />
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700,
        color: lc.color, letterSpacing: '0.1em', textTransform: 'uppercase',
      }}>
        {displayLevel}
      </span>
      <span style={{
        fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--label-tertiary)',
      }}>
        风险等级
      </span>
    </div>
  );
});

const InitBanner = memo(function InitBanner() {
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '10px 16px', borderRadius: 'var(--r-md)',
      background: 'rgba(10,132,255,0.08)', border: '1px solid rgba(10,132,255,0.2)',
    }}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0A84FF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>
      <span style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: '#0A84FF', flex: 1 }}>
        风控系统初始化中 — 数据将在后端服务就绪后自动加载
      </span>
      <button
        onClick={() => setVisible(false)}
        style={{
          background: 'none', border: 'none', cursor: 'pointer', padding: 2,
          color: 'var(--label-quaternary)', display: 'flex', alignItems: 'center',
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  );
});

const LoadingPlaceholder = memo(function LoadingPlaceholder() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      padding: '32px 0', gap: 12,
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: '50%',
        border: '2px solid rgba(10,132,255,0.2)',
        borderTopColor: '#0A84FF',
        animation: 'spin 1s linear infinite',
      }} />
      <span style={{
        fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--label-tertiary)',
        animation: 'subtleBreathe 2s ease-in-out infinite',
      }}>
        风控数据加载中
      </span>
    </div>
  );
});



const SectorExposureCanvas = memo(function SectorExposureCanvas({ sectors }: { sectors: Record<string, number> }) {
  const entries = Object.entries(sectors);
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    if (entries.length === 0) return;
    ctx.clearRect(0, 0, w, h);

    const labelWidth = 60;
    const valueWidth = 50;
    const barHeight = 14;
    const rowGap = 26;
    const barAreaW = w - labelWidth - valueWidth;
    const maxVal = Math.max(...entries.map(([, v]) => v), 0.01);

    for (let i = 0; i < entries.length; i++) {
      const [name, val] = entries[i]!;
      const y = i * rowGap;

      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.font = '12px -apple-system, BlinkMacSystemFont, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(name, labelWidth - 8, y + barHeight / 2 + 4);

      const barW = (val / maxVal) * barAreaW;
      const grad = ctx.createLinearGradient(labelWidth, 0, labelWidth + barW, 0);
      grad.addColorStop(0, 'rgba(10,132,255,0.15)');
      grad.addColorStop(1, 'rgba(10,132,255,0.55)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.roundRect(labelWidth, y + 2, barW, barHeight - 4, 3);
      ctx.fill();

      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.font = '10px SF Mono, JetBrains Mono, monospace';
      ctx.textAlign = 'left';
      ctx.fillText((val * 100).toFixed(1) + '%', labelWidth + barW + 4, y + barHeight / 2 + 3);
    }
  }, [entries]);

  const { ref } = useCanvas(draw, [entries]);
  return <canvas ref={ref} style={{ width: '100%', height: Math.max(entries.length * 26 + 8, 60) }} />;
});

const EfficientFrontierCanvas = memo(function EfficientFrontierCanvas({ frontier, minVariance, maxSharpe }: {
  frontier: FrontierPoint[];
  minVariance: FrontierPoint;
  maxSharpe: FrontierPoint;
}) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    if (frontier.length === 0) return;
    ctx.clearRect(0, 0, w, h);

    const padL = 56;
    const padR = 24;
    const padT = 16;
    const padB = 36;
    const chartW = w - padL - padR;
    const chartH = h - padT - padB;

    const vols = frontier.map(p => p.volatility);
    const rets = frontier.map(p => p.return);
    const minVol = Math.min(...vols) * 0.9;
    const maxVol = Math.max(...vols) * 1.1;
    const minRet = Math.min(...rets) * 0.9;
    const maxRet = Math.max(...rets) * 1.1;
    const volRange = maxVol - minVol || 0.01;
    const retRange = maxRet - minRet || 0.01;

    const toX = (vol: number) => padL + ((vol - minVol) / volRange) * chartW;
    const toY = (ret: number) => padT + chartH - ((ret - minRet) / retRange) * chartH;

    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    const xTicks = 5;
    const yTicks = 5;
    for (let i = 0; i <= xTicks; i++) {
      const vol = minVol + (volRange * i) / xTicks;
      const x = toX(vol);
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + chartH);
      ctx.stroke();
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.font = '9px SF Mono, JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText((vol * 100).toFixed(1) + '%', x, padT + chartH + 14);
    }
    for (let i = 0; i <= yTicks; i++) {
      const ret = minRet + (retRange * i) / yTicks;
      const y = toY(ret);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + chartW, y);
      ctx.stroke();
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.font = '9px SF Mono, JetBrains Mono, monospace';
      ctx.textAlign = 'right';
      ctx.fillText((ret * 100).toFixed(1) + '%', padL - 6, y + 3);
    }

    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '9px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('年化波动率', padL + chartW / 2, h - 2);

    ctx.save();
    ctx.translate(10, padT + chartH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillText('年化收益率', 0, 0);
    ctx.restore();

    const sorted = [...frontier].sort((a, b) => a.volatility - b.volatility);
    ctx.strokeStyle = 'rgba(10,132,255,0.7)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < sorted.length; i++) {
      const x = toX(sorted[i]!.volatility);
      const y = toY(sorted[i]!.return);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    for (const p of sorted) {
      ctx.fillStyle = 'rgba(10,132,255,0.5)';
      ctx.beginPath();
      ctx.arc(toX(p.volatility), toY(p.return), 2.5, 0, Math.PI * 2);
      ctx.fill();
    }

    const drawDiamond = (point: FrontierPoint, color: string) => {
      const cx = toX(point.volatility);
      const cy = toY(point.return);
      const s = 6;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(cx, cy - s);
      ctx.lineTo(cx + s, cy);
      ctx.lineTo(cx, cy + s);
      ctx.lineTo(cx - s, cy);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.6)';
      ctx.lineWidth = 1;
      ctx.stroke();
    };

    drawDiamond(minVariance, '#00C853');
    drawDiamond(maxSharpe, '#FF1744');
  }, [frontier, minVariance, maxSharpe]);

  const { ref } = useCanvas(draw, [frontier, minVariance, maxSharpe]);
  return <canvas ref={ref} style={{ width: '100%', height: 320 }} />;
});

const WeightBar = memo(function WeightBar({ symbol, weight }: { symbol: string; weight: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.7)', width: 56, flexShrink: 0 }}>
        {symbol}
      </span>
      <div style={{ flex: 1, height: 10, borderRadius: 3, background: 'rgba(255,255,255,0.06)' }}>
        <div style={{
          width: `${weight * 100}%`,
          height: '100%',
          borderRadius: 3,
          background: 'linear-gradient(to right, rgba(10,132,255,0.2), rgba(10,132,255,0.6))',
        }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(255,255,255,0.6)', width: 44, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {(weight * 100).toFixed(1)}%
      </span>
    </div>
  );
});

const OptimalPortfolioCard = memo(function OptimalPortfolioCard({ title, point, accentColor }: {
  title: string;
  point: FrontierPoint;
  accentColor: string;
}) {
  const weightEntries = Object.entries(point.weights);
  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      borderRadius: 'var(--r-md)',
      border: `1px solid ${accentColor}22`,
      padding: 16,
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
        color: accentColor, marginBottom: 12, letterSpacing: '0.04em',
      }}>
        {title}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>波动率</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: 'rgba(255,255,255,0.9)', fontVariantNumeric: 'tabular-nums' }}>
            {(point.volatility * 100).toFixed(2)}%
          </div>
        </div>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>收益率</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: 'rgba(255,255,255,0.9)', fontVariantNumeric: 'tabular-nums' }}>
            {(point.return * 100).toFixed(2)}%
          </div>
        </div>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>夏普比率</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: accentColor, fontVariantNumeric: 'tabular-nums' }}>
            {point.sharpe_ratio.toFixed(3)}
          </div>
        </div>
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
        权重配置
      </div>
      {weightEntries.map(([sym, w]) => (
        <WeightBar key={sym} symbol={sym} weight={w} />
      ))}
    </div>
  );
});

const EfficientFrontierPanel = memo(function EfficientFrontierPanel() {
  const { data, isLoading } = useEfficientFrontier();

  if (isLoading) return <LoadingPlaceholder />;
  if (!data || data.frontier.length === 0) return <EmptyState title="暂无有效前沿数据" description="请先添加持仓" size="md" />;

  return (
    <>
      <EfficientFrontierCanvas
        frontier={data.frontier}
        minVariance={data.optimal_portfolios.min_variance}
        maxSharpe={data.optimal_portfolios.max_sharpe}
      />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
        <OptimalPortfolioCard
          title="最小方差组合"
          point={data.optimal_portfolios.min_variance}
          accentColor="#00C853"
        />
        <OptimalPortfolioCard
          title="最大夏普组合"
          point={data.optimal_portfolios.max_sharpe}
          accentColor="#FF1744"
        />
      </div>
    </>
  );
});

const MonteCarloVaRCanvas = memo(function MonteCarloVaRCanvas({ data }: { data: MonteCarloVaRData }) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    ctx.clearRect(0, 0, w, h);
    const mu = data.mean_portfolio_return;
    const sigma = data.std_portfolio_return;
    if (sigma <= 0) return;
    const N_BINS = 60;
    const rangeMin = mu - 3.5 * sigma;
    const rangeMax = mu + 3.5 * sigma;
    const binW = (rangeMax - rangeMin) / N_BINS;
    const bins: number[] = [];
    for (let i = 0; i < N_BINS; i++) {
      const x = rangeMin + (i + 0.5) * binW;
      const pdf = Math.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * Math.sqrt(2 * Math.PI));
      bins.push(pdf * binW * data.n_simulations);
    }
    const padL = 56;
    const padR = 24;
    const padT = 20;
    const padB = 36;
    const chartW = w - padL - padR;
    const chartH = h - padT - padB;
    const maxFreq = Math.max(...bins, 0.01);
    const toX = (val: number) => padL + ((val - rangeMin) / (rangeMax - rangeMin)) * chartW;
    const toY = (freq: number) => padT + chartH - (freq / maxFreq) * chartH;

    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    const xTicks = 6;
    for (let i = 0; i <= xTicks; i++) {
      const val = rangeMin + ((rangeMax - rangeMin) * i) / xTicks;
      const x = toX(val);
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + chartH);
      ctx.stroke();
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.font = '9px SF Mono, JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText((val * 100).toFixed(1) + '%', x, padT + chartH + 14);
    }
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i++) {
      const freq = (maxFreq * i) / yTicks;
      const y = toY(freq);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + chartW, y);
      ctx.stroke();
    }

    const barPixelW = chartW / N_BINS;
    for (let i = 0; i < N_BINS; i++) {
      const binCenter = rangeMin + (i + 0.5) * binW;
      let color: string;
      if (binCenter < data.var_99) {
        color = '#FF1744';
      } else if (binCenter < data.var_95) {
        color = '#FF9100';
      } else {
        color = 'rgba(10,132,255,0.5)';
      }
      const barH = (bins[i]! / maxFreq) * chartH;
      if (barH < 1) continue;
      ctx.fillStyle = color;
      const x = padL + i * barPixelW;
      ctx.beginPath();
      ctx.roundRect(x + 0.5, padT + chartH - barH, barPixelW - 1, barH, 2);
      ctx.fill();
    }

    const drawVarLine = (value: number, label: string, color: string) => {
      const x = toX(value);
      if (x < padL || x > padL + chartW) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + chartH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = '10px SF Mono, JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(label, x, padT - 4);
    };

    drawVarLine(data.var_95, 'VaR 95%', '#FF9100');
    drawVarLine(data.var_99, 'VaR 99%', '#FF1744');

    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '9px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('收益率', padL + chartW / 2, h - 2);

    ctx.save();
    ctx.translate(10, padT + chartH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillText('频次', 0, 0);
    ctx.restore();
  }, [data]);

  const { ref } = useCanvas(draw, [data]);
  return <canvas ref={ref} style={{ width: '100%', height: 280 }} />;
});

const MonteCarloVaRPanel = memo(function MonteCarloVaRPanel() {
  const { data, isLoading } = useMonteCarloVaR();

  if (isLoading) return <LoadingPlaceholder />;
  if (!data) return <EmptyState title="暂无风险数据" description="请先添加持仓" size="md" />;

  const metrics: Array<{ label: string; value: string; color: string }> = [
    { label: 'VaR(95%)', value: (data.var_95 * 100).toFixed(2) + '%', color: '#FF9100' },
    { label: 'VaR(99%)', value: (data.var_99 * 100).toFixed(2) + '%', color: '#FF1744' },
    { label: 'CVaR(95%)', value: (data.cvar_95 * 100).toFixed(2) + '%', color: '#FF9100' },
    { label: 'CVaR(99%)', value: (data.cvar_99 * 100).toFixed(2) + '%', color: '#FF1744' },
    { label: '均值回报', value: (data.mean_portfolio_return * 100).toFixed(2) + '%', color: '#0A84FF' },
    { label: '标准差', value: (data.std_portfolio_return * 100).toFixed(2) + '%', color: 'rgba(255,255,255,0.9)' },
    { label: '模拟次数', value: data.n_simulations.toLocaleString(), color: 'rgba(255,255,255,0.9)' },
    { label: '方法', value: data.method, color: 'rgba(255,255,255,0.9)' },
  ];

  return (
    <>
      <MonteCarloVaRCanvas data={data} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginTop: 16 }}>
        {metrics.map(m => (
          <div key={m.label} style={{
            background: 'rgba(255,255,255,0.03)',
            borderRadius: 'var(--r-md)',
            border: '1px solid var(--separator)',
            padding: '12px 14px',
          }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
              {m.label}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: m.color, fontVariantNumeric: 'tabular-nums' }}>
              {m.value}
            </div>
          </div>
        ))}
      </div>
    </>
  );
});

const CorrelationPanel = memo(function CorrelationPanel() {
  const { data, isLoading } = useCorrelationMatrix();

  if (isLoading) return <LoadingPlaceholder />;
  if (!data) return <EmptyState title="暂无相关性数据" description="请先添加持仓" size="md" />;

  const symbols = data.symbols;
  const matrixValues = useMemo(() => symbols.map(row =>
    symbols.map(col => data.full_correlation[row]?.[col] ?? 0)
  ), [symbols, data.full_correlation]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: '1px solid var(--separator)', padding: '12px 14px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>分析期间</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: 'rgba(255,255,255,0.9)', fontVariantNumeric: 'tabular-nums' }}>{data.period}</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: '1px solid var(--separator)', padding: '12px 14px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>滚动窗口</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: 'rgba(255,255,255,0.9)', fontVariantNumeric: 'tabular-nums' }}>{data.rolling_window}天</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: '1px solid var(--separator)', padding: '12px 14px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>标的数量</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: 'rgba(255,255,255,0.9)', fontVariantNumeric: 'tabular-nums' }}>{data.symbols.length}</div>
        </div>
      </div>
      <ErrorBoundary fallback={<div style={{ color: 'var(--label-tertiary)', padding: 16 }}>Chart unavailable</div>}>
        <CorrelationMatrix labels={symbols} values={matrixValues} width={440} height={320} />
      </ErrorBoundary>
      <CorrelationLegend />
    </div>
  );
});

const BlackLittermanPanel = memo(function BlackLittermanPanel() {
  const { data, isLoading } = useBlackLitterman();

  if (isLoading) return <LoadingPlaceholder />;
  if (!data) return <EmptyState title="暂无优化数据" description="请先添加持仓" size="md" />;

  const weightEntries = Object.entries(data.weights);
  const returnEntries = Object.entries(data.posterior_returns);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: '1px solid var(--separator)', padding: '16px 14px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>预期收益率</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color: data.expected_return >= 0 ? '#00C853' : '#FF1744', fontVariantNumeric: 'tabular-nums' }}>
            {(data.expected_return * 100).toFixed(2)}%
          </div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: '1px solid var(--separator)', padding: '16px 14px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>预期波动率</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color: 'rgba(255,255,255,0.9)', fontVariantNumeric: 'tabular-nums' }}>
            {(data.expected_volatility * 100).toFixed(2)}%
          </div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: '1px solid var(--separator)', padding: '16px 14px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>夏普比率</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color: data.sharpe_ratio >= 1 ? '#00C853' : data.sharpe_ratio >= 0.5 ? '#FF9100' : '#FF1744', fontVariantNumeric: 'tabular-nums' }}>
            {data.sharpe_ratio.toFixed(3)}
          </div>
        </div>
      </div>

      <div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          优化权重
        </div>
        {weightEntries.map(([symbol, weight]) => (
          <div key={symbol} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '6px 0' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'rgba(255,255,255,0.7)', width: 64, flexShrink: 0 }}>
              {symbol}
            </span>
            <div style={{ flex: 1, height: 12, borderRadius: 4, background: 'rgba(255,255,255,0.06)' }}>
              <div style={{
                width: `${weight * 100}%`,
                height: '100%',
                borderRadius: 4,
                background: 'linear-gradient(to right, rgba(10,132,255,0.25), rgba(10,132,255,0.7))',
              }} />
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#0A84FF', width: 52, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
              {(weight * 100).toFixed(1)}%
            </span>
          </div>
        ))}
      </div>

      <div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          后验收益率
        </div>
        <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: '1px solid var(--separator)', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--separator)' }}>
                <th style={{ padding: '10px 14px', fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', textAlign: 'left', fontWeight: 500 }}>标的</th>
                <th style={{ padding: '10px 14px', fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', textAlign: 'right', fontWeight: 500 }}>后验收益率</th>
              </tr>
            </thead>
            <tbody>
              {returnEntries.map(([symbol, ret]) => (
                <tr key={symbol} style={{ borderBottom: '1px solid var(--separator)' }}>
                  <td style={{ padding: '10px 14px', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'rgba(255,255,255,0.9)' }}>
                    {symbol}
                  </td>
                  <td style={{ padding: '10px 14px', fontFamily: 'var(--font-mono)', fontSize: 12, color: ret >= 0 ? '#00C853' : '#FF1744', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {(ret * 100).toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
});

const KELLY_INPUT: React.CSSProperties = {
  width: '100%', height: 36, background: 'var(--bg-overlay)',
  border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)',
  padding: '0 10px', color: 'var(--label-primary)', fontFamily: 'var(--font-mono)',
  fontSize: 12, outline: 'none', boxSizing: 'border-box',
};

const KellyCalculatorPanel = memo(function KellyCalculatorPanel() {
  const [winRate, setWinRate] = useState('0.55');
  const [avgWin, setAvgWin] = useState('0.08');
  const [avgLoss, setAvgLoss] = useState('0.05');
  const [queryParams, setQueryParams] = useState({ winRate: 0.55, avgWin: 0.08, avgLoss: 0.05 });

  const { data, isLoading, isError } = useKellyCalculator(queryParams.winRate, queryParams.avgWin, queryParams.avgLoss);

  const handleCalculate = () => {
    setQueryParams({
      winRate: parseFloat(winRate),
      avgWin: parseFloat(avgWin),
      avgLoss: parseFloat(avgLoss),
    });
  };

  const kellyColor = (v: number) => {
    if (v > 0.25) return '#FF1744';
    if (v > 0.10) return '#FF9100';
    return '#00C853';
  };

  const fractionLabels: Record<string, string> = {
    full_kelly: '全 Kelly',
    half_kelly: '半 Kelly',
    quarter_kelly: '1/4 Kelly',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>胜率</div>
          <input value={winRate} onChange={e => setWinRate(e.target.value)} style={KELLY_INPUT} placeholder="0.55" />
        </div>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>平均盈利</div>
          <input value={avgWin} onChange={e => setAvgWin(e.target.value)} style={KELLY_INPUT} placeholder="0.08" />
        </div>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>平均亏损</div>
          <input value={avgLoss} onChange={e => setAvgLoss(e.target.value)} style={KELLY_INPUT} placeholder="0.05" />
        </div>
      </div>

      <button
        onClick={handleCalculate}
        disabled={isLoading}
        style={{
          height: 36, background: isLoading ? 'var(--bg-overlay)' : 'var(--accent)',
          color: isLoading ? 'var(--label-quaternary)' : '#fff',
          border: 'none', borderRadius: 'var(--r-sm)', cursor: isLoading ? 'not-allowed' : 'pointer',
          fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
          letterSpacing: '0.06em', transition: 'all var(--dur-fast)',
        }}
      >
        {isLoading ? '计算中...' : '计算 Kelly'}
      </button>

      {isError && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#FF1744', padding: '8px 12px', background: 'rgba(255,23,68,0.08)', borderRadius: 'var(--r-sm)', border: '1px solid rgba(255,23,68,0.2)' }}>
          计算失败，请检查参数
        </div>
      )}

      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: `1px solid ${kellyColor(data.kelly_full)}33`, padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>全 Kelly</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, color: kellyColor(data.kelly_full), fontVariantNumeric: 'tabular-nums' }}>
                {(data.kelly_full * 100).toFixed(1)}%
              </div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', border: '1px solid rgba(10,132,255,0.25)', padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                {fractionLabels[data.fraction_type] ?? data.fraction_type}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>
                {(data.suggested_fraction * 100).toFixed(1)}%
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {[
              { label: '盈亏比', value: data.win_loss_ratio.toFixed(2), color: '#0A84FF' },
              { label: '期望值', value: `${data.expected_value >= 0 ? '+' : ''}${(data.expected_value * 100).toFixed(2)}%`, color: data.expected_value >= 0 ? '#00C853' : '#FF1744' },
              { label: '破产概率', value: `${(data.ruin_probability * 100).toFixed(1)}%`, color: data.ruin_probability > 0.1 ? '#FF1744' : data.ruin_probability > 0.05 ? '#FF9100' : '#00C853' },
              { label: '最大仓位', value: `${data.max_position_pct.toFixed(0)}%`, color: '#FF9100' },
            ].map(m => (
              <div key={m.label} style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-sm)', padding: '10px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{m.label}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: m.color, fontVariantNumeric: 'tabular-nums' }}>{m.value}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

const StressTestPanel = memo(function StressTestPanel() {
  const [symbols, setSymbols] = useState('000001.SZ,000002.SZ,600519.SH');
  const { isLoading: scenariosLoading } = useStressScenarios();
  const stressTest = useRunStressTest();

  const handleRunStressTest = () => {
    stressTest.mutate(symbols.split(',').map(s => s.trim()));
  };

  const scenarioColors: Record<string, string> = {
    '2008金融危机': '#FF1744', '2020疫情冲击': '#FF9100',
    '利率骤升': '#FFEA00', '黑天鹅事件': '#FF4081', '温和回调': '#00C853',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          value={symbols}
          onChange={e => setSymbols(e.target.value)}
          placeholder="000001.SZ,000002.SZ,600519.SH"
          style={{ flex: 1, height: 32, background: 'var(--bg-overlay)', border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)', padding: '0 10px', color: 'var(--label-primary)', fontFamily: 'var(--font-mono)', fontSize: 10, outline: 'none' }}
        />
        <button
          onClick={handleRunStressTest}
          disabled={stressTest.isPending || scenariosLoading}
          style={{ height: 32, padding: '0 14px', borderRadius: 'var(--r-sm)', border: 'none', background: stressTest.isPending ? 'var(--bg-overlay)' : 'var(--accent)', color: stressTest.isPending ? 'rgba(255,255,255,0.4)' : '#fff', fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, cursor: stressTest.isPending ? 'not-allowed' : 'pointer' }}
        >
          {stressTest.isPending ? '运行中...' : '压力测试'}
        </button>
      </div>

      {scenariosLoading && <div style={{ height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>加载场景...</span></div>}

      {stressTest.data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {[
              { label: '最坏情况', value: `${(stressTest.data.summary.worst_case * 100).toFixed(1)}%`, color: '#FF1744' },
              { label: '平均影响', value: `${(stressTest.data.summary.average_impact * 100).toFixed(1)}%`, color: '#FF9100' },
              { label: '压力得分', value: stressTest.data.summary.stress_score.toFixed(0), color: stressTest.data.summary.stress_score > 70 ? '#FF1744' : stressTest.data.summary.stress_score > 40 ? '#FF9100' : '#00C853' },
            ].map(m => (
              <div key={m.label} style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-sm)', padding: '10px 8px', border: `1px solid ${m.color}33` }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)', textTransform: 'uppercase', marginBottom: 4 }}>{m.label}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: m.color, fontVariantNumeric: 'tabular-nums' }}>{m.value}</div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {stressTest.data.scenarios.map(s => (
              <div key={s.name} style={{ background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--r-sm)', padding: '10px 12px', borderLeft: `3px solid ${scenarioColors[s.name] ?? '#666'}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, color: 'var(--label-primary)' }}>{s.name}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: s.portfolio_impact < -0.1 ? '#FF1744' : s.portfolio_impact < -0.05 ? '#FF9100' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                    {(s.portfolio_impact * 100).toFixed(1)}%
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'rgba(255,255,255,0.4)' }}>波动率 {(s.portfolio_volatility * 100).toFixed(1)}%</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'rgba(255,255,255,0.4)' }}>回撤 {(s.max_drawdown * 100).toFixed(1)}%</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'rgba(255,255,255,0.4)' }}>恢复 {s.recovery_days}天</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

const DiversificationPanel = memo(function DiversificationPanel() {
  const [data, setData] = useState<DiversificationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [symbols, setSymbols] = useState('000001.SZ,000002.SZ,600519.SH');

  const fetchData = () => {
    let cancelled = false;
    setLoading(true); setError(false);
    apiGet<DiversificationData>('/portfolio/diversification', { symbols: symbols.split(',').map(s => s.trim()) })
      .then(res => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch(() => { if (!cancelled) { setError(true); setLoading(false); } });
    return () => { cancelled = true; };
  };

  useEffect(() => { fetchData(); }, []);

  const scoreColor = (v: number) => v > 0.7 ? '#00C853' : v > 0.4 ? '#FF9100' : '#FF1744';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input value={symbols} onChange={e => setSymbols(e.target.value)} placeholder="股票代码,逗号分隔"
          style={{ flex: 1, height: 32, background: 'var(--bg-overlay)', border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)', padding: '0 10px', color: 'var(--label-primary)', fontFamily: 'var(--font-mono)', fontSize: 10, outline: 'none' }} />
        <button onClick={fetchData} disabled={loading} style={{ height: 32, padding: '0 14px', borderRadius: 'var(--r-sm)', border: 'none', background: loading ? 'var(--bg-overlay)' : 'var(--accent)', color: loading ? 'rgba(255,255,255,0.4)' : '#fff', fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer' }}>
          {loading ? '...' : '查询'}
        </button>
      </div>

      {error && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#FF1744', padding: '8px 12px', background: 'rgba(255,23,68,0.08)', borderRadius: 'var(--r-sm)' }}>数据不足，请检查股票代码</div>}

      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-md)', padding: '16px 14px', border: `1px solid ${scoreColor(data.diversification_score)}33` }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', marginBottom: 6 }}>分散化得分</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 36, fontWeight: 700, color: scoreColor(data.diversification_score), fontVariantNumeric: 'tabular-nums' }}>
              {(data.diversification_score * 100).toFixed(0)}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'rgba(255,255,255,0.4)', marginTop: 4 }}>/ 100</div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
            <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-sm)', padding: '12px 10px' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)', textTransform: 'uppercase', marginBottom: 4 }}>平均相关性</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: data.avg_correlation > 0.7 ? '#FF1744' : data.avg_correlation > 0.4 ? '#FF9100' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                {data.avg_correlation.toFixed(3)}
              </div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--r-sm)', padding: '12px 10px' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)', textTransform: 'uppercase', marginBottom: 4 }}>集中度风险</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: data.concentration_risk > 0.7 ? '#FF1744' : data.concentration_risk > 0.4 ? '#FF9100' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                {(data.concentration_risk * 100).toFixed(0)}%
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

const PortfolioAttributionPanel = memo(function PortfolioAttributionPanel() {
  const [data, setData] = useState<AttributionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [symbols, setSymbols] = useState('000001.SZ,000002.SZ,600519.SH');

  const fetchData = () => {
    let cancelled = false;
    setLoading(true); setError(false);
    apiGet<AttributionData>('/portfolio/attribution', { symbols: symbols.split(',').map(s => s.trim()) })
      .then(res => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch(() => { if (!cancelled) { setError(true); setLoading(false); } });
    return () => { cancelled = true; };
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input value={symbols} onChange={e => setSymbols(e.target.value)} placeholder="股票代码,逗号分隔"
          style={{ flex: 1, height: 32, background: 'var(--bg-overlay)', border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)', padding: '0 10px', color: 'var(--label-primary)', fontFamily: 'var(--font-mono)', fontSize: 10, outline: 'none' }} />
        <button onClick={fetchData} disabled={loading} style={{ height: 32, padding: '0 14px', borderRadius: 'var(--r-sm)', border: 'none', background: loading ? 'var(--bg-overlay)' : 'var(--accent)', color: loading ? 'rgba(255,255,255,0.4)' : '#fff', fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer' }}>
          {loading ? '...' : '查询'}
        </button>
      </div>

      {error && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#FF1744', padding: '8px 12px', background: 'rgba(255,23,68,0.08)', borderRadius: 'var(--r-sm)' }}>数据不足</div>}

      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', padding: '0 4px' }}>
            收益贡献分解
          </div>
          {data.symbols.map(sym => {
            const contrib = data.contribution[sym] ?? 0;
            const barWidth = Math.min(Math.abs(contrib) * 300, 100);
            return (
              <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(255,255,255,0.6)', width: 80, flexShrink: 0 }}>{sym}</span>
                <div style={{ flex: 1, height: 16, background: 'rgba(0,0,0,0.3)', borderRadius: 'var(--r-xs)', position: 'relative', overflow: 'hidden' }}>
                  <div style={{
                    position: 'absolute', top: 0, height: '100%',
                    width: `${barWidth}%`,
                    left: contrib >= 0 ? '50%' : `${50 - barWidth}%`,
                    background: contrib >= 0 ? 'rgba(255,23,68,0.6)' : 'rgba(0,200,83,0.6)',
                    borderRadius: 'var(--r-xs)',
                  }} />
                  <div style={{ position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)', fontFamily: 'var(--font-mono)', fontSize: 8, color: 'rgba(255,255,255,0.7)', fontVariantNumeric: 'tabular-nums' }}>
                    {(contrib * 100).toFixed(2)}%
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});

const RISK_PANEL: React.CSSProperties = {
  background: 'var(--bg-glass)',
  backdropFilter: 'blur(24px) saturate(120%)',
  borderRadius: 'var(--r-lg)',
  border: '1px solid var(--separator)',
  padding: 20,
};

const RISK_PANEL_TITLE: React.CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: 15,
  fontWeight: 600,
  color: 'var(--label-primary)',
  marginBottom: 16,
};

export function RiskPage() {
  const alerts = useRiskStore(s => s.alerts);
  const { data: dashboardData } = usePortfolioRiskDashboard();
  const { data: portfolioData, isLoading: portfolioLoading } = useRiskPortfolio();
  const { data: exposureData, isLoading: exposureLoading } = useRiskExposure();
  const { data: drawdownData, isLoading: drawdownLoading } = useDrawdownAnalysis('000001');

  const rm = dashboardData?.risk_metrics;
  const var95 = rm?.var_95 ?? 0;
  const cvar = rm?.cvar_95 ?? 0;
  const maxDrawdown = rm?.max_drawdown ?? 0;
  const sharpe = rm?.portfolio_sharpe ?? 0;
  const beta = 1;
  const riskLevel: RiskLevel = var95 > 0.05 || maxDrawdown > 0.15 ? 'HIGH' : var95 > 0.03 || maxDrawdown > 0.08 ? 'MEDIUM' : 'LOW';
  const metrics: RiskMetrics | null = dashboardData ? {
    riskLevel,
    var95,
    cvar,
    maxDrawdown,
    sharpe,
    beta,
    riskDecomposition: [],
    correlationMatrix: { labels: [], values: [[]] },
    historicalVol: [],
    impliedVol: [],
    volDates: [],
  } : null;

  const loading = isDataLoading(var95, cvar, maxDrawdown, sharpe, beta);

  const decomposition = metrics?.riskDecomposition ?? FALLBACK_DECOMPOSITION;
  const correlation = metrics?.correlationMatrix ?? FALLBACK_CORRELATION;
  const volDates = metrics?.volDates ?? FALLBACK_VOL_DATES;
  const historicalVol = metrics?.historicalVol ?? FALLBACK_HISTORICAL_VOL;
  const impliedVol = metrics?.impliedVol ?? FALLBACK_IMPLIED_VOL;

  const topMetrics: Array<{ label: string; value: string; color: string; subtitle: string; borderColor: BorderColor }> = [
    { label: 'VaR(95%)', value: formatRatio(var95), color: metricColor(var95), subtitle: 'Value at Risk', borderColor: varBorderColor(var95) },
    { label: 'CVaR', value: formatRatio(cvar), color: metricColor(cvar), subtitle: 'Conditional VaR', borderColor: varBorderColor(cvar) },
    { label: 'MAX DRAWDOWN', value: formatRatio(maxDrawdown), color: metricColor(maxDrawdown, true), subtitle: 'Peak to Trough', borderColor: '#FF1744' },
    { label: 'SHARPE', value: sharpe.toFixed(2), color: metricColor(sharpe), subtitle: 'Risk-Adj Return', borderColor: sharpeBorderColor(sharpe) },
    { label: 'BETA', value: beta.toFixed(2), color: beta > 1 ? '#FF9100' : '#00C853', subtitle: 'Market Sensitivity', borderColor: betaBorderColor(beta) },
  ];

  const effectiveRiskLevel: RiskLevel = loading ? 'LOW' : riskLevel;

  return (
    <>
      <style>{pulseKeyframes}{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{ minHeight: '100%', background: '#000000', padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
        {loading && <InitBanner />}

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <RiskLevelBadge level={effectiveRiskLevel} isLoading={loading} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-quaternary)', letterSpacing: '0.04em' }}>
            RISK MONITOR
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
          <GaugeCard value={var95} max={0.15} label="VaR(95%)" unit="%" />
          <GaugeCard value={cvar} max={0.20} label="CVaR" unit="%" />
          <GaugeCard value={maxDrawdown} max={0.30} label="MAX DD" unit="%" />
          <GaugeCard value={sharpe} max={3} label="SHARPE" unit="" />
          <GaugeCard value={beta} max={2} label="BETA" unit="" />
        </div>

        {loading && <LoadingPlaceholder />}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div style={RISK_PANEL}>
            <div style={RISK_PANEL_TITLE}>风险分解</div>
            <DecompositionCanvas data={decomposition} />
          </div>
          <div style={RISK_PANEL}>
            <div style={RISK_PANEL_TITLE}>相关性矩阵</div>
            <ErrorBoundary fallback={<div style={{ color: 'var(--label-tertiary)', padding: 16 }}>Chart unavailable</div>}>
              <CorrelationMatrix labels={correlation.labels} values={correlation.values} width={440} height={320} />
            </ErrorBoundary>
            <CorrelationLegend />
          </div>
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>波动率分析</div>
          <VolatilityCone dates={volDates} historical={historicalVol} implied={impliedVol} width={900} height={200} />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>投资组合风险</div>
          {portfolioLoading ? <LoadingPlaceholder /> : !portfolioData ? <EmptyState title="暂无风险数据" description="请先添加持仓" size="md" /> : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>持仓数量</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: 'rgba(255,255,255,0.95)', fontVariantNumeric: 'tabular-nums' }}>
                  {portfolioData.position_count}
                </div>
              </div>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>VaR(95%)</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: metricColor(portfolioData.var_95), fontVariantNumeric: 'tabular-nums' }}>
                  {formatRatio(portfolioData.var_95)}
                </div>
              </div>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>CVaR(95%)</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: metricColor(portfolioData.cvar_95), fontVariantNumeric: 'tabular-nums' }}>
                  {formatRatio(portfolioData.cvar_95)}
                </div>
              </div>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>年化波动率</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: metricColor(portfolioData.annualized_vol), fontVariantNumeric: 'tabular-nums' }}>
                  {formatRatio(portfolioData.annualized_vol)}
                </div>
              </div>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Beta</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: portfolioData.beta > 1 ? '#FF9100' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {portfolioData.beta.toFixed(4)}
                </div>
              </div>
              <div style={{ gridColumn: 'span 3' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>持仓标的</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {portfolioData.symbols.map(sym => (
                    <span key={sym} style={{
                      fontFamily: 'var(--font-mono)', fontSize: 11, padding: '4px 10px',
                      borderRadius: 'var(--r-xs)', background: 'rgba(10,132,255,0.12)',
                      color: '#0A84FF', border: '1px solid rgba(10,132,255,0.2)',
                    }}>
                      {sym}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>风险暴露度</div>
          {exposureLoading ? <LoadingPlaceholder /> : !exposureData ? <EmptyState title="暂无风险数据" description="请先添加持仓" size="md" /> : (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  行业分布
                </div>
                <SectorExposureCanvas sectors={exposureData.sectors} />
              </div>
              <div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>集中度</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: exposureData.concentration > 0.5 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                      {(exposureData.concentration * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>分散化评分</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: metricColor(exposureData.diversification_score), fontVariantNumeric: 'tabular-nums' }}>
                      {(exposureData.diversification_score * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>持仓数量</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: 'rgba(255,255,255,0.95)', fontVariantNumeric: 'tabular-nums' }}>
                      {exposureData.position_count}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>回撤分析</div>
          {drawdownLoading ? <LoadingPlaceholder /> : !drawdownData ? <EmptyState title="暂无风险数据" description="请先添加持仓" size="md" /> : (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>标的</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>
                    {drawdownData.symbol}
                  </div>
                </div>
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>回撤次数</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: 'rgba(255,255,255,0.95)', fontVariantNumeric: 'tabular-nums' }}>
                    {drawdownData.total_episodes}
                  </div>
                </div>
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>恢复率</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: drawdownData.recovery_rate >= 0.8 ? '#00C853' : '#FF9100', fontVariantNumeric: 'tabular-nums' }}>
                    {(drawdownData.recovery_rate * 100).toFixed(0)}%
                  </div>
                </div>
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>平均恢复周期</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700, color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>
                    {drawdownData.avg_recovery_bars.toFixed(1)}根
                  </div>
                </div>
              </div>
              {drawdownData.episodes.length > 0 && (
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    回撤周期 (Top 5)
                  </div>
                  {(() => {
                    const maxDepth = Math.max(...drawdownData.episodes.map(e => Math.abs(e.depth)), 0.01);
                    return drawdownData.episodes.slice(0, 5).map((ep, idx) => {
                      const depthPct = Math.abs(ep.depth) / maxDepth;
                      return (
                        <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--separator)' }}>
                          <span style={{
                            fontFamily: 'var(--font-mono)', fontSize: 9, padding: '2px 6px',
                            borderRadius: 'var(--r-xs)',
                            background: ep.recovered ? 'rgba(0,200,83,0.12)' : 'rgba(255,23,68,0.12)',
                            color: ep.recovered ? '#00C853' : '#FF1744',
                            flexShrink: 0,
                          }}>
                            {ep.recovered ? '已恢复' : '未恢复'}
                          </span>
                          <div style={{ flex: 1, height: 8, borderRadius: 4, background: 'rgba(255,255,255,0.06)' }}>
                            <div style={{ width: `${depthPct * 100}%`, height: '100%', borderRadius: 4, background: 'linear-gradient(to right, rgba(255,23,68,0.2), rgba(255,23,68,0.6))' }} />
                          </div>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#FF1744', width: 60, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                            {(ep.depth * 100).toFixed(1)}%
                          </span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(255,255,255,0.35)', width: 100, flexShrink: 0 }}>
                            持续{ep.duration_bars}根 恢复{ep.recovery_bars}根
                          </span>
                        </div>
                      );
                    });
                  })()}
                </div>
              )}
            </>
          )}
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>有效前沿</div>
          <EfficientFrontierPanel />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>蒙特卡洛 VaR</div>
          <MonteCarloVaRPanel />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>相关性矩阵</div>
          <CorrelationPanel />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>Black-Litterman 优化</div>
          <BlackLittermanPanel />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>Kelly 仓位计算器</div>
          <KellyCalculatorPanel />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>压力测试</div>
          <StressTestPanel />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>分散化分析</div>
          <DiversificationPanel />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>收益归因</div>
          <PortfolioAttributionPanel />
        </div>

        <div style={RISK_PANEL}>
          <div style={RISK_PANEL_TITLE}>风险警报</div>
          <AlertTimeline alerts={alerts} />
        </div>
      </div>
    </>
  );
}
