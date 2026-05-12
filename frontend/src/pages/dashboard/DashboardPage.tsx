import { useEffect, useState, useMemo, memo, useCallback } from 'react';
import { apiGet } from '@/api/client';
import { useMarketOverview, useMarketStocks, useMarketSectors } from '@/hooks/queries/useMarketQueries';
import { usePortfolioRiskDashboard } from '@/hooks/queries/usePortfolioQueries';
import { useWatchlist } from '@/hooks/queries/useWatchlistQueries';
import { useReadiness } from '@/hooks/queries/useSystemQueries';
import { Sparkline } from '@/components/charts/Sparkline';
import { HeatmapCanvas } from '@/components/charts/HeatmapCanvas';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { RiskBanner } from '@/components/ui/RiskBanner';
import { SignalBadge } from '@/components/ui/SignalBadge';
import { formatPercent, priceColor } from '@/utils/format';
import type { IndexQuote, SectorData, SignalItem } from '@/types';

interface ReadinessResponse {
  status: string;
  checks: Record<string, string>;
  timestamp: string;
}

interface SystemMetricsResponse {
  api_caches: Record<string, {
    size: number;
    maxsize: number;
    hits: number;
    misses: number;
    hit_rate: number;
  }>;
}

interface DataSourceHealth {
  sources: Record<string, {
    state: string;
    failure_count: number;
    last_failure: string | null;
  }>;
}

interface CacheStats {
  caches: Record<string, {
    size: number;
    maxsize: number;
    hits: number;
    misses: number;
    hit_rate: number;
  }>;
}

interface PortfolioDashboardData {
  positions: Array<{ symbol: string; name: string; price: number; change_pct: number; market: string }>;
  total_value: number;
  daily_pnl_pct: number;
  position_count: number;
  risk_metrics: {
    portfolio_volatility: number;
    portfolio_sharpe: number;
    portfolio_sortino: number;
    var_95: number;
    cvar_95: number;
    max_drawdown: number;
    annual_return: number;
  };
  concentration: Record<string, number>;
  drawdown: { current_drawdown: number; max_drawdown: number; drawdown_status: string };
  stress_summary: Array<{ scenario: string; description: string; projected_loss_pct: number; projected_loss_amount: number }>;
}

interface MarketBreadthData {
  advance_count: number;
  decline_count: number;
  up: number;
  down: number;
  flat: number;
  total_amount: number;
  timestamp: number;
  temperature?: number;
}

interface MarketOverviewData {
  cn_indices: Record<string, { name: string; price: number; change_pct: number; change: number }>;
  hk_indices: Record<string, { name: string; price: number; change_pct: number; change: number }>;
  us_indices: Record<string, { name: string; price: number; change_pct: number; change: number }>;
  temperature: number;
  timestamp: number;
  market_breadth: MarketBreadthData | null;
}

const DEFAULT_INDICES: IndexQuote[] = [
  { name: '上证指数', code: 'sh000001', price: 0, change: 0, change_pct: 0 },
  { name: '深证成指', code: 'sz399001', price: 0, change: 0, change_pct: 0 },
  { name: '创业板指', code: 'sz399006', price: 0, change: 0, change_pct: 0 },
  { name: '沪深300', code: 'sh000300', price: 0, change: 0, change_pct: 0 },
  { name: '中证500', code: 'sh000905', price: 0, change: 0, change_pct: 0 },
  { name: '科创50', code: 'sh000688', price: 0, change: 0, change_pct: 0 },
];

const IndexCard = memo(function IndexCard({ idx }: { idx: IndexQuote }) {
  const isRise = idx.change_pct >= 0;
  const sparkData = useMemo(
    () => Array.from({ length: 16 }, (_, j) => {
      const t = j / 15;
      const trend = idx.change_pct > 0 ? 0.4 * t : idx.change_pct < 0 ? -0.4 * t : 0;
      return trend + Math.sin(j * 1.8 + idx.change_pct * 8) * 0.25 + Math.sin(j * 3.1 + idx.change_pct * 4) * 0.12;
    }),
    [idx.change_pct],
  );

  return (
    <div style={{
      flex: '0 0 auto',
      width: '180px',
      height: '80px',
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--s3)',
      padding: '0 var(--s4)',
      background: 'var(--bg-glass)',
      backdropFilter: 'blur(24px) saturate(120%)',
      borderRadius: 'var(--r-md)',
      border: '1px solid var(--separator)',
    }}>
      <Sparkline
        data={sparkData}
        width={44}
        height={20}
        color={isRise ? '#FF1744' : '#00C853'}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 }}>
        <span style={{
          fontFamily: 'var(--font-sans)',
          fontSize: '11px',
          color: 'var(--label-tertiary)',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}>
          {idx.name}
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '18px',
          fontWeight: 600,
          color: priceColor(idx.change_pct),
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1.2,
        }}>
          {idx.price != null ? idx.price.toFixed(2) : '—'}
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '10px',
          padding: '1px 6px',
          borderRadius: 'var(--r-xs)',
          background: isRise ? 'var(--rise-bg)' : 'var(--fall-bg)',
          color: priceColor(idx.change_pct),
          fontVariantNumeric: 'tabular-nums',
          alignSelf: 'flex-start',
          letterSpacing: '0.02em',
        }}>
          {idx.change_pct != null ? formatPercent(idx.change_pct) : ''}
        </span>
      </div>
    </div>
  );
});

const HeroTickerBar = memo(function HeroTickerBar({ indices }: { indices: IndexQuote[] }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--s3)',
      padding: 'var(--s4) var(--s6)',
      overflowX: 'auto',
      WebkitOverflowScrolling: 'touch',
    }}>
      {indices.map((idx, i) => (
        <IndexCard key={idx.code || i} idx={idx} />
      ))}
    </div>
  );
});

const AnimatedRiskBanner = memo(function AnimatedRiskBanner({
  level,
  maxDrawdown,
  alertCount,
}: {
  level: string;
  maxDrawdown: number;
  alertCount: number;
}) {
  const visible = level === 'MEDIUM' || level === 'HIGH' || level === 'CRITICAL';
  return (
    <div style={{
      height: visible ? '44px' : '0px',
      overflow: 'hidden',
      transition: 'height var(--dur-base) var(--ease-apple)',
    }}>
      <RiskBanner level={level as 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'} maxDrawdown={maxDrawdown} alertCount={alertCount} />
    </div>
  );
});

const PortfolioDashboardPanel = memo(function PortfolioDashboardPanel() {
  const [data, setData] = useState<PortfolioDashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiGet<PortfolioDashboardData>('/portfolio/risk/dashboard').then(d => {
      if (!cancelled) { setData(d); setLoading(false); }
    }).catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) return <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.3)' }}>LOADING...</span></div>;
  if (!data) return null;

  if (!('risk_metrics' in data)) {
    const positions = data as Array<{ symbol: string; name: string; price: number; change_pct: number; market: string }>;
    if (positions.length === 0) {
      return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 120, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.3)' }}>暂无持仓数据</div>;
    }
    return (
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {positions.slice(0, 8).map(p => (
          <div key={p.symbol} style={{ flex: '0 0 auto', background: 'var(--bg-elevated)', borderRadius: 'var(--r-sm)', padding: '10px 14px', minWidth: 100 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent)', marginBottom: 4 }}>{p.symbol}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, color: p.change_pct >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
              {p.change_pct >= 0 ? '+' : ''}{p.change_pct.toFixed(2)}%
            </div>
          </div>
        ))}
      </div>
    );
  }

  const { risk_metrics, concentration, drawdown, positions } = data;
  const isConcentrated = concentration._is_concentrated ?? false;
  const topSymbol = Object.entries(concentration).find(([k]) => !k.startsWith('_'))?.[0] ?? '';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        {[
          { label: '年化收益', value: `${(risk_metrics.annual_return * 100).toFixed(1)}%`, color: risk_metrics.annual_return >= 0 ? '#FF1744' : '#00C853' },
          { label: '夏普比率', value: risk_metrics.portfolio_sharpe.toFixed(2), color: risk_metrics.portfolio_sharpe >= 1 ? '#00C853' : risk_metrics.portfolio_sharpe >= 0.5 ? '#FF9100' : '#FF1744' },
          { label: 'Sortino', value: risk_metrics.portfolio_sortino.toFixed(2), color: '#0A84FF' },
          { label: '波动率', value: `${(risk_metrics.portfolio_volatility * 100).toFixed(1)}%`, color: '#FF9100' },
        ].map(m => (
          <div key={m.label} style={{ background: 'var(--bg-elevated)', borderRadius: 'var(--r-sm)', padding: '10px 8px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)', textTransform: 'uppercase', marginBottom: 4 }}>{m.label}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 700, color: m.color, fontVariantNumeric: 'tabular-nums' }}>{m.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div style={{ background: 'var(--bg-elevated)', borderRadius: 'var(--r-sm)', padding: '10px 12px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)', textTransform: 'uppercase', marginBottom: 6 }}>VaR / CVaR (95%)</div>
          <div style={{ display: 'flex', gap: 16 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: '#FF1744', fontVariantNumeric: 'tabular-nums' }}>{(risk_metrics.var_95 * 100).toFixed(1)}%</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: '#FF9100', fontVariantNumeric: 'tabular-nums' }}>{(risk_metrics.cvar_95 * 100).toFixed(1)}%</span>
          </div>
        </div>
        <div style={{ background: 'var(--bg-elevated)', borderRadius: 'var(--r-sm)', padding: '10px 12px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)', textTransform: 'uppercase', marginBottom: 6 }}>最大回撤 / 当前回撤</div>
          <div style={{ display: 'flex', gap: 16 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: '#00C853', fontVariantNumeric: 'tabular-nums' }}>{(drawdown.max_drawdown * 100).toFixed(1)}%</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>{(drawdown.current_drawdown * 100).toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {isConcentrated && (
        <div style={{ background: 'rgba(255,23,68,0.08)', border: '1px solid rgba(255,23,68,0.25)', borderRadius: 'var(--r-sm)', padding: '10px 12px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: '#FF1744', textTransform: 'uppercase', marginBottom: 4 }}>⚠ 集中度警告</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.7)' }}>
            {topSymbol} 占比 <strong style={{ color: '#FF1744' }}>{((concentration[topSymbol] ?? 0) * 100).toFixed(1)}%</strong>，建议分散持仓
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        {positions.slice(0, 4).map(p => (
          <div key={p.symbol} style={{ flex: 1, background: 'var(--bg-elevated)', borderRadius: 'var(--r-sm)', padding: '8px 10px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent)', marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.symbol}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, color: p.change_pct >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
              {p.change_pct >= 0 ? '+' : ''}{p.change_pct.toFixed(2)}%
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

const MarketBreadthPanel = memo(function MarketBreadthPanel({ data }: { data: MarketOverviewData | null }) {
  if (!data?.market_breadth) return <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.3)' }}>NO DATA</span></div>;

  const { up, down, flat } = data.market_breadth;
  const total = up + down + flat;
  const upPct = total > 0 ? (up / total) * 100 : 0;
  const breadthColor = upPct > 60 ? '#FF1744' : upPct < 40 ? '#00C853' : '#FF9100';
  const temperature = data.temperature;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {[
          { label: '上涨', value: up, color: '#FF1744' },
          { label: '下跌', value: down, color: '#00C853' },
          { label: '平盘', value: flat, color: '#888' },
        ].map(m => (
          <div key={m.label} style={{ background: 'var(--bg-elevated)', borderRadius: 'var(--r-sm)', padding: '10px 8px', textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)', textTransform: 'uppercase', marginBottom: 4 }}>{m.label}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color: m.color, fontVariantNumeric: 'tabular-nums' }}>{m.value}</div>
          </div>
        ))}
      </div>
      <div style={{ height: 8, background: 'rgba(0,0,0,0.3)', borderRadius: 'var(--r-xs)', overflow: 'hidden', display: 'flex' }}>
        <div style={{ width: `${upPct}%`, background: '#FF1744', transition: 'width 0.3s' }} />
        <div style={{ width: `${total > 0 ? (down / total) * 100 : 0}%`, background: '#00C853', transition: 'width 0.3s' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', textTransform: 'uppercase' }}>市场温度</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: breadthColor, fontVariantNumeric: 'tabular-nums' }}>{temperature?.toFixed(0)}°</div>
      </div>
    </div>
  );
});

const GlobalIndicesPanel = memo(function GlobalIndicesPanel({ data }: { data: MarketOverviewData | null }) {
  if (!data) return <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.3)' }}>NO DATA</span></div>;

  const allIndices = useMemo(() => [
    ...Object.entries(data.cn_indices ?? {}).map(([k, v]) => ({ ...v, code: k })),
    ...Object.entries(data.hk_indices ?? {}).map(([k, v]) => ({ ...v, code: k })),
    ...Object.entries(data.us_indices ?? {}).map(([k, v]) => ({ ...v, code: k })),
  ], [data.cn_indices, data.hk_indices, data.us_indices]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {allIndices.slice(0, 8).map(idx => (
        <div key={idx.code} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(255,255,255,0.7)' }}>{idx.name}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'rgba(255,255,255,0.3)' }}>{idx.code}</span>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600, color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>{idx.price.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: idx.change_pct >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
              {idx.change_pct >= 0 ? '+' : ''}{idx.change_pct.toFixed(2)}%
            </div>
          </div>
        </div>
      ))}
    </div>
  );
});

const SystemHealthPanel = memo(function SystemHealthPanel() {
  const [dsHealth, setDsHealth] = useState<DataSourceHealth | null>(null);
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      apiGet<ReadinessResponse>('/readiness'),
      apiGet<SystemMetricsResponse>('/system/metrics'),
    ]).then(([readinessResult, metricsResult]) => {
      if (cancelled) return;
      if (readinessResult.status === 'fulfilled') {
        const checks = readinessResult.value.checks;
        const sources: DataSourceHealth['sources'] = {};
        for (const [name, state] of Object.entries(checks)) {
          sources[name] = {
            state: state === 'ready' ? 'OPEN' : 'CLOSED',
            failure_count: state === 'ready' ? 0 : 1,
            last_failure: state === 'ready' ? null : readinessResult.value.timestamp,
          };
        }
        setDsHealth({ sources });
      }
      if (metricsResult.status === 'fulfilled') {
        setCacheStats({ caches: metricsResult.value.api_caches });
      }
    });
    return () => { cancelled = true; };
  }, []);

  const sourceEntries = useMemo(
    () => dsHealth ? Object.entries(dsHealth.sources) : [],
    [dsHealth],
  );

  const cacheEntries = useMemo(
    () => cacheStats ? Object.entries(cacheStats.caches) : [],
    [cacheStats],
  );

  return (
    <div style={{
      background: 'var(--bg-glass)',
      backdropFilter: 'blur(24px) saturate(120%)',
      borderRadius: 'var(--r-lg)',
      border: '1px solid var(--separator)',
      overflow: 'hidden',
    }}>
      <div style={SECTION_LABEL}>系统状态</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0' }}>
        <div style={{ borderRight: '1px solid var(--separator)' }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '9px',
            color: 'var(--label-quaternary)',
            letterSpacing: '0.08em',
            padding: 'var(--s3) var(--s5)',
            borderBottom: '1px solid var(--separator)',
            textTransform: 'uppercase',
          }}>
            数据源
          </div>
          {sourceEntries.length === 0 ? (
            <div style={{ padding: 'var(--s5)', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-quaternary)' }}>
              —
            </div>
          ) : (
            sourceEntries.map(([name, info]) => (
              <div
                key={name}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--s3)',
                  padding: '8px var(--s5)',
                  borderBottom: '1px solid var(--separator)',
                }}
              >
                <span style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: info.state === 'OPEN' ? '#00C853' : '#FF1744',
                  flexShrink: 0,
                  boxShadow: info.state === 'OPEN'
                    ? '0 0 6px rgba(0,200,83,0.5)'
                    : '0 0 6px rgba(255,23,68,0.5)',
                }} />
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--label-primary)',
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {name}
                </span>
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '10px',
                  color: info.failure_count > 0 ? '#FF1744' : 'var(--label-quaternary)',
                  fontVariantNumeric: 'tabular-nums',
                }}>
                  {info.failure_count} failures
                </span>
              </div>
            ))
          )}
        </div>
        <div>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '9px',
            color: 'var(--label-quaternary)',
            letterSpacing: '0.08em',
            padding: 'var(--s3) var(--s5)',
            borderBottom: '1px solid var(--separator)',
            textTransform: 'uppercase',
          }}>
            缓存
          </div>
          {cacheEntries.length === 0 ? (
            <div style={{ padding: 'var(--s5)', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-quaternary)' }}>
              —
            </div>
          ) : (
            cacheEntries.map(([name, info]) => {
              const fillPct = info.maxsize > 0 ? (info.size / info.maxsize) * 100 : 0;
              const barColor = fillPct > 90 ? '#FF1744' : fillPct > 70 ? '#FF9100' : '#0A84FF';
              return (
                <div
                  key={name}
                  style={{
                    padding: '8px var(--s5)',
                    borderBottom: '1px solid var(--separator)',
                  }}
                >
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: '4px',
                  }}>
                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '11px',
                      color: 'var(--label-primary)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {name}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '10px',
                      color: 'var(--label-tertiary)',
                      fontVariantNumeric: 'tabular-nums',
                    }}>
                      {info.size}/{info.maxsize}
                    </span>
                  </div>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--s3)',
                  }}>
                    <div style={{
                      flex: 1,
                      height: '4px',
                      borderRadius: 'var(--r-pill)',
                      background: 'rgba(255,255,255,0.08)',
                      overflow: 'hidden',
                    }}>
                      <div style={{
                        width: `${Math.min(fillPct, 100)}%`,
                        height: '100%',
                        borderRadius: 'var(--r-pill)',
                        background: barColor,
                        transition: 'width var(--dur-base) var(--ease-apple)',
                      }} />
                    </div>
                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '10px',
                      color: 'var(--label-tertiary)',
                      fontVariantNumeric: 'tabular-nums',
                      width: '40px',
                      textAlign: 'right',
                    }}>
                      {(info.hit_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
});

const GLASS_PANEL: React.CSSProperties = {
  background: 'var(--bg-glass)',
  backdropFilter: 'blur(24px) saturate(120%)',
  borderRadius: 'var(--r-lg)',
  border: '1px solid var(--separator)',
  overflow: 'hidden',
};

const SECTION_LABEL: React.CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: '13px',
  fontWeight: 600,
  color: 'var(--label-primary)',
  padding: 'var(--s3) var(--s5)',
  borderBottom: '1px solid var(--separator)',
  letterSpacing: '0.01em',
};

const NorthboundFlowCard = memo(function NorthboundFlowCard({ northFlow }: { northFlow: number | null }) {
  if (northFlow == null) return null;
  const isPositive = northFlow >= 0;
  const direction = northFlow >= 0 ? '净流入' : '净流出';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 'var(--s4)', padding: 'var(--s4) var(--s5)',
      background: 'var(--bg-glass)', backdropFilter: 'blur(24px) saturate(120%)',
      borderRadius: 'var(--r-md)', border: '1px solid var(--separator)',
    }}>
      <Sparkline data={[0.2, 0.1, -0.1, 0.3, 0.5, 0.4, 0.6]} width={48} height={20} color={isPositive ? '#FF1744' : '#00C853'} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#666666', letterSpacing: '0.04em' }}>北向资金{direction}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', fontWeight: 600, color: isPositive ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
          {northFlow >= 0 ? '+' : ''}{northFlow.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}亿
        </span>
      </div>
    </div>
  );
});

const SignalList = memo(function SignalList({ signals }: { signals: SignalItem[] }) {
  if (signals.length === 0) return <div style={{ padding: 'var(--s5)', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-quaternary)' }}>暂无信号</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {signals.map(s => (
        <div key={s.symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px var(--s5)', borderBottom: '1px solid var(--separator)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'var(--label-tertiary)' }}>{s.name}</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
            <SignalBadge action={s.action} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: s.change_pct >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
              {s.change_pct >= 0 ? '+' : ''}{s.change_pct.toFixed(2)}%
            </span>
          </div>
        </div>
      ))}
      <div style={{
        padding: '8px var(--s5)',
        borderTop: '1px solid var(--separator)',
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          padding: '2px 6px',
          borderRadius: 'var(--r-xs)',
          background: 'rgba(255,145,0,0.12)',
          color: 'var(--orange)',
          letterSpacing: '0.04em',
        }}>
          ⚠
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)', letterSpacing: '0.03em' }}>
          Client-derived signals — verify T-1 alignment
        </span>
      </div>
    </div>
  );
});

const UnusualActivity = memo(function UnusualActivity({ stocks }: { stocks: Array<{ symbol: string; name: string; change_pct: number; volume_ratio?: number; turnover?: number }> }) {
  const unusual = useMemo(() => stocks.filter(s => (s.volume_ratio ?? 0) > 3 || Math.abs(s.change_pct) > 9).slice(0, 6), [stocks]);
  if (unusual.length === 0) return <div style={{ padding: 'var(--s5)', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-quaternary)' }}>暂无异动</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {unusual.map(s => (
        <div key={s.symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px var(--s5)', borderBottom: '1px solid var(--separator)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: s.change_pct >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'var(--label-tertiary)' }}>{s.name}</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: s.change_pct >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
              {s.change_pct >= 0 ? '+' : ''}{s.change_pct.toFixed(2)}%
            </span>
            {s.volume_ratio && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.4)' }}>量比 {s.volume_ratio.toFixed(1)}x</span>}
          </div>
        </div>
      ))}
    </div>
  );
});

const WatchlistPanel = memo(function WatchlistPanel({ stocks }: { stocks: Array<{ symbol: string; name: string; price: number; change_pct: number }> }) {
  if (stocks.length === 0) return <div style={{ padding: 'var(--s5)', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-quaternary)' }}>暂无自选股</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {stocks.slice(0, 6).map(s => (
        <div key={s.symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px var(--s5)', borderBottom: '1px solid var(--separator)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>{s.symbol}</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'var(--label-tertiary)' }}>{s.name}</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>
              {s.price?.toFixed(2) ?? '—'}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: s.change_pct >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
              {s.change_pct >= 0 ? '+' : ''}{s.change_pct.toFixed(2)}%
            </span>
          </div>
        </div>
      ))}
    </div>
  );
});

const AISummaryCard = memo(function AISummaryCard() {
  return (
    <div style={{ background: 'var(--bg-glass)', backdropFilter: 'blur(24px) saturate(120%)', borderRadius: 'var(--r-lg)', border: '1px solid var(--separator)', padding: 'var(--s5)', display: 'flex', gap: 'var(--s4)', alignItems: 'flex-start' }}>
      <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: '#fff', fontWeight: 700 }}>Q</span>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>市场摘要</div>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'rgba(255,255,255,0.6)', lineHeight: 1.6 }}>
          当前市场整体偏震荡格局，量能有所萎缩。科技板块表现相对强势，消费板块出现分化，建议关注业绩确定性较强的标的。操作上保持仓位控制，等待趋势明朗。
        </div>
      </div>
    </div>
  );
});

export function DashboardPage() {
  const { data: marketData } = useMarketOverview();
  const { data: stocks = [] } = useMarketStocks('A');
  const { data: sectors = {} } = useMarketSectors();
  const { data: watchlistData } = useWatchlist();
  const { data: riskDashboard } = usePortfolioRiskDashboard();
  const { data: systemHealth } = useReadiness();
  const [systemExpanded, setSystemExpanded] = useState(false);

  const watchlistSymbols = watchlistData?.symbols ?? [];
  const indices = useMemo(() => {
    if (!marketData?.cn_indices) return [];
    return Object.entries(marketData.cn_indices).map(([code, v]) => ({
      name: v.name,
      code,
      price: v.price,
      change: v.change,
      change_pct: v.change_pct,
    }));
  }, [marketData?.cn_indices]);
  const northFlow = marketData?.northbound?.total_net ?? null;
  const riskLevel = riskDashboard?.drawdown?.drawdown_status === 'critical' ? 'HIGH' : 
                    riskDashboard?.drawdown?.drawdown_status === 'warning' ? 'MEDIUM' : 'LOW';
  const maxDrawdown = riskDashboard?.risk_metrics?.max_drawdown ?? 0;
  const alerts = riskDashboard?.stress_summary?.map(s => s.scenario) ?? [];

  const displayIndices = useMemo(() => {
    if (indices.length > 0) return indices;
    return DEFAULT_INDICES;
  }, [indices]);

  const signals = useMemo(() => {
    if (stocks.length === 0) return [];
    return stocks.slice(0, 12).map(s => ({
      symbol: s.symbol,
      name: s.name,
      action: s.change_pct > 1 ? 'BUY' as const : s.change_pct < -1 ? 'SELL' as const : 'HOLD' as const,
      change_pct: s.change_pct,
      confidence: Math.min(Math.abs(s.change_pct) * 20, 100),
    }));
  }, [stocks]);

  const watchlistStocks = useMemo(
    () => stocks.filter(s => watchlistSymbols.includes(s.symbol)),
    [stocks, watchlistSymbols],
  );

  const sectorList = useMemo<SectorData[]>(() => {
    if (!sectors) return [];
    const maybeItems = (sectors as Record<string, unknown>).items;
    if (Array.isArray(maybeItems)) return maybeItems as SectorData[];
    return Object.entries(sectors).map(([key, val]) => ({
      name: val?.name ?? key,
      change_pct: val?.change_pct ?? 0,
      amount: val?.amount ?? val?.volume ?? 0,
      volume: val?.volume ?? 0,
    }));
  }, [sectors]);

  const toggleSystem = useCallback(() => setSystemExpanded(v => !v), []);

  return (
    <div style={{ background: 'var(--bg-base)', minHeight: '100%', display: 'flex', flexDirection: 'column', padding: 'var(--s6)' }}>
      <div style={{ ...GLASS_PANEL, marginBottom: '16px' }}>
        <HeroTickerBar indices={displayIndices} />
        <div style={{ borderTop: '1px solid var(--separator)', padding: '0 var(--s6)' }}>
          <NorthboundFlowCard northFlow={northFlow} />
        </div>
      </div>

      <AnimatedRiskBanner
        level={riskLevel}
        maxDrawdown={maxDrawdown}
        alertCount={alerts.length}
      />

      <div style={{
        display: 'grid',
        gridTemplateColumns: '45fr 30fr 25fr',
        gap: '16px',
        padding: '0 24px',
        flex: 1,
      }}>
        <div style={{ ...GLASS_PANEL, display: 'flex', flexDirection: 'column' }}>
          <div style={SECTION_LABEL}>板块热力</div>
          <div style={{ flex: 1, padding: 'var(--s4)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <ErrorBoundary fallback={<div style={{ color: 'var(--label-tertiary)', padding: 16 }}>Chart unavailable</div>}>
              <HeatmapCanvas sectors={sectorList} />
            </ErrorBoundary>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ ...GLASS_PANEL }}>
            <div style={SECTION_LABEL}>市场广度</div>
            <MarketBreadthPanel data={marketData} />
          </div>
          <div style={{ ...GLASS_PANEL, flex: 1 }}>
            <div style={SECTION_LABEL}>全球指数</div>
            <GlobalIndicesPanel data={marketData} />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ ...GLASS_PANEL }}>
            <div style={SECTION_LABEL}>实时信号</div>
            <SignalList signals={signals} />
          </div>
          <div style={{ ...GLASS_PANEL, flex: 1 }}>
            <div style={SECTION_LABEL}>异动行情</div>
            <UnusualActivity stocks={stocks} />
          </div>
        </div>
      </div>

      <div style={{ padding: '24px 24px 0' }}>
        <div style={{ ...GLASS_PANEL, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={SECTION_LABEL}>组合概览</div>
          <PortfolioDashboardPanel />
        </div>
      </div>

      <div style={{ padding: '0 24px' }}>
        <button
          onClick={toggleSystem}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: '12px 0',
            fontFamily: 'var(--font-sans)',
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--label-tertiary)',
            letterSpacing: '0.01em',
          }}
        >
          <span style={{
            display: 'inline-block',
            transition: 'transform 0.2s ease',
            transform: systemExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
            fontSize: 10,
          }}>▶</span>
          系统状态 & AI摘要
        </button>
        <div style={{
          overflow: 'hidden',
          maxHeight: systemExpanded ? '2000px' : '0px',
          transition: 'max-height 0.3s ease',
        }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingBottom: 24 }}>
            <AISummaryCard />
            <SystemHealthPanel />
          </div>
        </div>
      </div>
    </div>
  );
}
