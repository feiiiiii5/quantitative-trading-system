import { useEffect, useState, useRef } from 'react';
import { useStrategyStore } from '@/stores/strategy';
import { formatRatio, formatPrice } from '@/utils/format';
import type { BacktestResult } from '@/types';

type Difficulty = 'BASIC' | 'PRO' | 'EXPERT';

function getDifficulty(name: string): Difficulty {
  const expert = ['ml_', 'deep_', 'lstm', 'transformer', 'gan', 'reinforcement', 'alpha', 'multi_factor', 'pair'];
  const pro = ['dual_ma', 'macd', 'kdj', 'bollinger', 'rsi', 'turtle', 'momentum', 'mean_reversion', 'breakout'];
  const lower = name.toLowerCase();
  if (expert.some(e => lower.includes(e))) return 'EXPERT';
  if (pro.some(e => lower.includes(e))) return 'PRO';
  return 'BASIC';
}

function DifficultyTag({ level }: { level: Difficulty }) {
  const colors: Record<Difficulty, { bg: string; color: string }> = {
    BASIC: { bg: 'rgba(91,168,160,0.12)', color: '#5BA8A0' },
    PRO: { bg: 'rgba(212,160,74,0.12)', color: '#D4A04A' },
    EXPERT: { bg: 'rgba(155,125,184,0.12)', color: '#9B7DB8' },
  };
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase',
      letterSpacing: '0.06em', padding: '1px 6px', borderRadius: '2px',
      background: colors[level].bg, color: colors[level].color,
    }}>
      {level}
    </span>
  );
}

function EquityCanvas({ data, showDrawdown }: { data: Array<{ date: string; value: number }>; showDrawdown: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width;
    const h = rect.height;
    const pad = { top: 16, right: 16, bottom: 28, left: 16 };
    const values = data.map(d => d.value);
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const range = maxVal - minVal || 1;
    ctx.clearRect(0, 0, w, h);

    ctx.strokeStyle = 'rgba(255,255,255,0.02)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (i / 4) * (h - pad.top - pad.bottom);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
    }

    const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
    gradient.addColorStop(0, 'rgba(201,169,110,0.08)');
    gradient.addColorStop(1, 'rgba(201,169,110,0)');
    ctx.beginPath();
    ctx.moveTo(pad.left, h - pad.bottom);
    for (let i = 0; i < values.length; i++) {
      const x = pad.left + (i / (values.length - 1)) * (w - pad.left - pad.right);
      const y = pad.top + (1 - (values[i]! - minVal) / range) * (h - pad.top - pad.bottom);
      ctx.lineTo(x, y);
    }
    ctx.lineTo(pad.left + (w - pad.left - pad.right), h - pad.bottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.beginPath();
    for (let i = 0; i < values.length; i++) {
      const x = pad.left + (i / (values.length - 1)) * (w - pad.left - pad.right);
      const y = pad.top + (1 - (values[i]! - minVal) / range) * (h - pad.top - pad.bottom);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = '#C9A96E';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    if (showDrawdown && values.length > 1) {
      let peak = values[0]!;
      const drawdowns = values.map(v => {
        if (v > peak) peak = v;
        return (v - peak) / peak;
      });
      const ddMin = Math.min(...drawdowns);
      const ddGradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
      ddGradient.addColorStop(0, 'rgba(212,88,74,0)');
      ddGradient.addColorStop(1, 'rgba(212,88,74,0.08)');
      ctx.beginPath();
      const baseline = pad.top + (1 - 0) * (h - pad.top - pad.bottom);
      ctx.moveTo(pad.left, baseline);
      for (let i = 0; i < drawdowns.length; i++) {
        const x = pad.left + (i / (drawdowns.length - 1)) * (w - pad.left - pad.right);
        const y = pad.top + (1 - drawdowns[i]! / ddMin) * (h - pad.top - pad.bottom) * 0.3 + baseline * 0.7;
        ctx.lineTo(x, y);
      }
      ctx.lineTo(pad.left + (w - pad.left - pad.right), baseline);
      ctx.closePath();
      ctx.fillStyle = ddGradient;
      ctx.fill();
    }

    const dateLabels = [0, Math.floor(values.length / 4), Math.floor(values.length / 2), Math.floor(values.length * 3 / 4), values.length - 1];
    ctx.font = '10px JetBrains Mono';
    ctx.textAlign = 'center';
    for (const idx of dateLabels) {
      const x = pad.left + (idx / (values.length - 1)) * (w - pad.left - pad.right);
      const dateStr = data[idx]?.date?.slice(0, 7) ?? '';
      ctx.fillStyle = '#3A3633';
      ctx.fillText(dateStr, x, h - 6);
    }
  }, [data, showDrawdown]);
  return <canvas ref={canvasRef} style={{ width: '100%', height: 280 }} />;
}

function TradeTable({ trades }: { trades: Array<Record<string, unknown>> }) {
  if (!trades || trades.length === 0) return null;
  return (
    <div style={{ marginTop: 24 }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase',
        letterSpacing: '0.08em', color: '#5E5854', padding: '0 0 10px 0',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
      }}>
        TRADE DETAILS ({trades.length})
      </div>
      <div style={{ maxHeight: '300px', overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['DATE', 'TYPE', 'PRICE', 'QTY', 'P&L'].map(h => (
                <th key={h} style={{
                  padding: '8px 12px', textAlign: 'left',
                  fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase',
                  letterSpacing: '0.08em', color: '#5E5854',
                  background: '#050505', borderBottom: '1px solid rgba(255,255,255,0.04)',
                  position: 'sticky', top: 0, zIndex: 1,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.slice(0, 50).map((t, i) => {
              const type = (t.type ?? t.action ?? '') as string;
              const isBuy = type.toLowerCase().includes('buy');
              return (
                <tr key={i} style={{ height: '32px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#9B9490' }}>{String(t.date ?? t.entry_date ?? '')}</td>
                  <td style={{ padding: '0 12px' }}>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase',
                      letterSpacing: '0.06em', padding: '1px 6px', borderRadius: '2px',
                      background: isBuy ? 'rgba(212,88,74,0.06)' : 'rgba(78,158,110,0.06)',
                      color: isBuy ? '#D4584A' : '#4E9E6E',
                    }}>
                      {isBuy ? 'BUY' : 'SELL'}
                    </span>
                  </td>
                  <td style={{ padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#F0EBE3', fontVariantNumeric: 'tabular-nums' }}>{formatPrice(Number(t.price ?? t.entry_price ?? 0))}</td>
                  <td style={{ padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#9B9490', fontVariantNumeric: 'tabular-nums' }}>{String(t.quantity ?? t.shares ?? '')}</td>
                  <td style={{ padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', fontVariantNumeric: 'tabular-nums', color: Number(t.pnl ?? t.profit ?? 0) >= 0 ? '#D4584A' : '#4E9E6E' }}>
                    {formatRatio(Number(t.pnl ?? t.profit ?? t.return ?? 0))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BacktestResults({ result, showDrawdown, onToggleDrawdown }: { result: BacktestResult; showDrawdown: boolean; onToggleDrawdown: () => void }) {
  const metrics: Array<[string, string, string]> = [
    ['TOTAL RETURN', formatRatio(result.total_return), result.total_return >= 0 ? '#D4584A' : '#4E9E6E'],
    ['ANNUAL RETURN', formatRatio(result.annual_return), result.annual_return >= 0 ? '#D4584A' : '#4E9E6E'],
    ['SHARPE RATIO', result.sharpe_ratio.toFixed(2), result.sharpe_ratio >= 1 ? '#D4584A' : '#D4A04A'],
    ['MAX DRAWDOWN', formatRatio(result.max_drawdown), '#4E9E6E'],
    ['WIN RATE', formatRatio(result.win_rate), result.win_rate >= 0.5 ? '#D4584A' : '#D4A04A'],
    ['PROFIT FACTOR', result.profit_factor.toFixed(2), result.profit_factor >= 1 ? '#D4584A' : '#4E9E6E'],
    ['TOTAL TRADES', result.total_trades.toString(), '#F0EBE3'],
    ['CALMAR RATIO', result.calmar_ratio.toFixed(2), '#F0EBE3'],
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1px', background: 'rgba(255,255,255,0.02)', marginBottom: 24 }}>
        {metrics.map(([label, value, color]) => (
          <div key={label} style={{ background: '#0a0a0a', padding: '14px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em', color: '#5E5854' }}>{label}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', fontWeight: 600, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
          </div>
        ))}
      </div>
      {result.equity_curve && result.equity_curve.length > 0 && (
        <div style={{ background: '#0a0a0a', borderRadius: 6, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.08em', color: '#9B9490' }}>EQUITY CURVE</span>
            <button
              onClick={onToggleDrawdown}
              style={{
                fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase',
                letterSpacing: '0.06em', padding: '2px 8px', borderRadius: '2px',
                background: showDrawdown ? 'rgba(212,88,74,0.06)' : 'transparent',
                color: showDrawdown ? '#D4584A' : '#5E5854',
                border: `1px solid ${showDrawdown ? 'rgba(212,88,74,0.15)' : 'rgba(255,255,255,0.04)'}`,
                cursor: 'pointer',
                transition: 'all 160ms ease-out',
              }}
            >
              DRAWDOWN
            </button>
          </div>
          <div style={{ padding: '8px 4px 4px' }}>
            <EquityCanvas data={result.equity_curve} showDrawdown={showDrawdown} />
          </div>
        </div>
      )}
      {result.trades && result.trades.length > 0 && (
        <TradeTable trades={result.trades} />
      )}
    </div>
  );
}

export function StrategyPage() {
  const { strategies, selectedStrategy, backtestResult, backtestRunning, backtestLogs, fetchStrategies, selectStrategy, runBacktest, clearResult } = useStrategyStore();
  const [symbol, setSymbol] = useState('000001.SZ');
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2025-12-31');
  const [capital, setCapital] = useState('1000000');
  const [showDrawdown, setShowDrawdown] = useState(false);

  useEffect(() => { fetchStrategies(); }, [fetchStrategies]);

  const handleRun = () => {
    if (!selectedStrategy) return;
    runBacktest({ symbol, start_date: startDate, end_date: endDate, initial_capital: Number(capital) });
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', height: '40px', background: '#0a0a0a',
    border: '1px solid rgba(255,255,255,0.06)', borderRadius: 6,
    padding: '0 12px', color: '#F0EBE3', fontFamily: 'var(--font-mono)',
    fontSize: '12px', outline: 'none', boxSizing: 'border-box',
    transition: 'border-color 160ms ease-out',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block', fontFamily: 'var(--font-mono)', fontSize: '9px',
    textTransform: 'uppercase', letterSpacing: '0.08em', color: '#5E5854',
    marginBottom: 4,
  };

  return (
    <div style={{ display: 'flex', height: '100%', background: '#000000' }}>
      <div style={{ width: 300, flexShrink: 0, background: '#050505', borderRight: '1px solid rgba(255,255,255,0.04)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
          <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 18, color: '#C9A96E', letterSpacing: '0.02em' }}>策略引擎</span>
        </div>
        <div style={{ flex: 1, overflow: 'auto' }}>
          {strategies.map((s) => {
            const diff = getDifficulty(s.name);
            const isActive = selectedStrategy === s.name;
            return (
              <div
                key={s.name}
                onClick={() => { selectStrategy(s.name); clearResult(); }}
                style={{
                  padding: '10px 20px', cursor: 'pointer',
                  borderLeft: isActive ? '2px solid #C9A96E' : '2px solid transparent',
                  background: isActive ? 'rgba(201,169,110,0.06)' : 'transparent',
                  transition: 'all 160ms ease-out',
                }}
                onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.015)'; }}
                onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: 12,
                    color: isActive ? '#C9A96E' : '#F0EBE3', flex: 1,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{s.name}</span>
                  <DifficultyTag level={diff} />
                </div>
                <div style={{
                  fontFamily: 'var(--font-sans)', fontSize: 11, color: '#5E5854',
                  marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>{s.description}</div>
              </div>
            );
          })}
        </div>

        <div style={{ padding: 20, borderTop: '1px solid rgba(255,255,255,0.04)', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={labelStyle}>SYMBOL</label>
            <input value={symbol} onChange={(e) => setSymbol(e.target.value)} style={inputStyle} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <label style={labelStyle}>START</label>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>END</label>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={inputStyle} />
            </div>
          </div>
          <div>
            <label style={labelStyle}>CAPITAL</label>
            <input value={capital} onChange={(e) => setCapital(e.target.value)} style={inputStyle} />
          </div>
          <button
            onClick={handleRun}
            disabled={backtestRunning || !selectedStrategy}
            style={{
              width: '100%', height: 48,
              background: backtestRunning || !selectedStrategy ? '#161616' : '#C9A96E',
              color: backtestRunning || !selectedStrategy ? '#3A3633' : '#000000',
              border: 'none', borderRadius: 6,
              fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 600,
              letterSpacing: '0.05em', cursor: backtestRunning || !selectedStrategy ? 'not-allowed' : 'pointer',
              transition: 'background 160ms ease-out',
            }}
            onMouseEnter={(e) => { if (!backtestRunning && selectedStrategy) e.currentTarget.style.background = '#D4B578'; }}
            onMouseLeave={(e) => { if (!backtestRunning && selectedStrategy) e.currentTarget.style.background = '#C9A96E'; }}
          >
            {backtestRunning ? 'RUNNING...' : 'RUN BACKTEST'}
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 32 }}>
        {backtestRunning ? (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: '#5E5854', lineHeight: '1.8' }}>
            {backtestLogs.map((log, i) => (
              <div key={i} style={{ animation: 'fade-in 280ms ease-out' }}>{log}</div>
            ))}
            <span style={{ animation: 'pulse-dot 1s ease-in-out infinite' }}>▌</span>
          </div>
        ) : backtestResult ? (
          <BacktestResults result={backtestResult} showDrawdown={showDrawdown} onToggleDrawdown={() => setShowDrawdown(v => !v)} />
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
            <pre style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '13px', color: '#3A3633', lineHeight: '1.7', textAlign: 'left', letterSpacing: '0.02em' }}>
{`┌──────────────────────────────────┐
│                                  │
│         Q                        │
│                                  │
│     SELECT STRATEGY              │
│                                  │
│     > ▌                          │
│                                  │
└──────────────────────────────────┘`}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
