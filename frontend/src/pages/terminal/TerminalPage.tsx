import { useState, useCallback, useEffect, useRef, useMemo, memo } from 'react';
import { useCanvas } from '@/hooks/useCanvas';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { EmptyState } from '@/components/ui/EmptyState';
import { SkeletonCard } from '@/components/ui/Skeleton';
import { DepthChart } from '@/components/charts/DepthChart';
import { useTerminalStore } from '@/stores/terminal';
import { useRiskStore } from '@/stores/risk';
import { useTradingHistory } from '@/hooks/queries';
import { usePnLWebSocket } from '@/hooks/usePnLWebSocket';
import { apiGet, apiPost } from '@/api/client';
import { formatPrice, formatVolume, formatAmount } from '@/utils/format';
import type { OrderBookEntry, TradeRecord } from '@/types';

function useExecutionStats() {
  const [stats, setStats] = useState<{ vwap: number; twap: number; avgSlippage: number; fillRate: number } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiGet<{
      total_trades?: number;
      win_rate?: number;
      sharpe_ratio?: number;
      avg_win?: number;
      avg_loss?: number;
    }>('/trading/analytics')
      .then((data: { total_trades?: number; win_rate?: number; sharpe_ratio?: number; avg_win?: number; avg_loss?: number }) => {
        if (cancelled) return;
        const totalTrades = data?.total_trades ?? 0;
        const winRate = (data?.win_rate ?? 0) * 100;
        const sharpe = data?.sharpe_ratio ?? 0;
        const avgWin = data?.avg_win ?? 0;
        setStats({
          vwap: sharpe > 0 ? sharpe : 0,
          twap: totalTrades > 0 ? totalTrades : 0,
          avgSlippage: avgWin > 0 ? avgWin : 0,
          fillRate: winRate > 0 ? winRate : 0,
        });
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  return { stats, loading };
}

const panelStyle: React.CSSProperties = {
  background: 'var(--bg-glass)',
  backdropFilter: 'blur(24px) saturate(120%)',
  borderRadius: 'var(--r-lg)',
  border: '1px solid var(--separator)',
  overflow: 'hidden',
};

const panelTitleStyle: React.CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: 15,
  fontWeight: 600,
  color: 'var(--label-primary)',
  padding: '16px 20px',
  borderBottom: '1px solid var(--separator)',
};

const OrderBookCanvas = memo(function OrderBookCanvas({ bids, asks }: { bids: OrderBookEntry[]; asks: OrderBookEntry[] }) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    ctx.clearRect(0, 0, w, h);
    if (bids.length === 0 && asks.length === 0) {
      ctx.font = '11px SF Mono, JetBrains Mono, monospace';
      ctx.fillStyle = 'rgba(255,255,255,0.20)';
      ctx.textAlign = 'center';
      ctx.fillText('NO DATA', w / 2, h / 2);
      return;
    }

    const rootStyle = getComputedStyle(document.documentElement);
    const numPositive = rootStyle.getPropertyValue('--num-positive').trim() || '#FF3B5C';
    const numNegative = rootStyle.getPropertyValue('--num-negative').trim() || '#00D9A0';
    const hexToRgba = (hex: string, a: number) => {
      const r = parseInt(hex.slice(1, 3), 16);
      const g = parseInt(hex.slice(3, 5), 16);
      const b = parseInt(hex.slice(5, 7), 16);
      return `rgba(${r},${g},${b},${a})`;
    };

    const maxVolume = Math.max(
      ...bids.map(b => b.quantity),
      ...asks.map(a => a.quantity),
      1,
    );

    const padding = { left: 72, right: 64, top: 8, bottom: 32 };
    const midGap = 22;
    const rowHeight = (h - padding.top - padding.bottom - midGap) / 20;
    const barMaxWidth = w - padding.left - padding.right;

    for (let i = 0; i < 10; i++) {
      const y = padding.top + i * rowHeight;
      const ask = asks[i];
      if (!ask) continue;
      const isBest = i === 0;
      const volBarW = (ask.quantity / maxVolume) * barMaxWidth;

      ctx.fillStyle = isBest ? hexToRgba(numNegative, 0.25) : 'rgba(0,200,83,0.12)';
      ctx.fillRect(padding.left, y, volBarW, rowHeight - 2);

      ctx.font = isBest ? 'bold 14px SF Mono, JetBrains Mono, monospace' : '11px SF Mono, JetBrains Mono, monospace';
      ctx.fillStyle = isBest ? numNegative : 'rgba(0,200,83,0.75)';
      ctx.textAlign = 'right';
      ctx.fillText(formatPrice(ask.price), padding.left - 8, y + rowHeight * 0.72);
      ctx.textAlign = 'left';
      ctx.fillStyle = isBest ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.45)';
      ctx.fillText(String(ask.quantity), padding.left + volBarW + 6, y + rowHeight * 0.72);
    }

    const spreadY = padding.top + 10 * rowHeight;
    const firstAsk = asks[0];
    const firstBid = bids[0];
    if (firstAsk && firstBid) {
      const spread = firstAsk.price - firstBid.price;
      const midPrice = (firstAsk.price + firstBid.price) / 2;
      const spreadPct = midPrice !== 0 ? ((spread / midPrice) * 100).toFixed(2) : '0.00';

      const pillW = 120;
      const pillH = 18;
      const pillX = (w - pillW) / 2;
      const pillY = spreadY + (midGap - pillH) / 2;
      ctx.fillStyle = 'rgba(10,132,255,0.12)';
      ctx.beginPath();
      ctx.roundRect(pillX, pillY, pillW, pillH, 9);
      ctx.fill();
      ctx.font = '10px SF Mono, JetBrains Mono, monospace';
      ctx.fillStyle = '#0A84FF';
      ctx.textAlign = 'center';
      ctx.fillText(`${midPrice.toFixed(2)}`, w / 2, pillY + 13);

      ctx.font = '9px SF Mono, JetBrains Mono, monospace';
      ctx.fillStyle = 'rgba(255,255,255,0.3)';
      ctx.textAlign = 'center';
      ctx.fillText(`SPREAD ${spread.toFixed(2)} (${spreadPct}%)`, w / 2, spreadY + midGap - 1);
    }

    for (let i = 0; i < 10; i++) {
      const y = spreadY + midGap + i * rowHeight;
      const bid = bids[i];
      if (!bid) continue;
      const isBest = i === 0;
      const volBarW = (bid.quantity / maxVolume) * barMaxWidth;

      ctx.fillStyle = isBest ? hexToRgba(numPositive, 0.25) : 'rgba(255,23,68,0.12)';
      ctx.fillRect(padding.left, y, volBarW, rowHeight - 2);

      ctx.font = isBest ? 'bold 14px SF Mono, JetBrains Mono, monospace' : '11px SF Mono, JetBrains Mono, monospace';
      ctx.fillStyle = isBest ? numPositive : 'rgba(255,23,68,0.75)';
      ctx.textAlign = 'right';
      ctx.fillText(formatPrice(bid.price), padding.left - 8, y + rowHeight * 0.72);
      ctx.textAlign = 'left';
      ctx.fillStyle = isBest ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.45)';
      ctx.fillText(String(bid.quantity), padding.left + volBarW + 6, y + rowHeight * 0.72);
    }

    const totalBid = bids.reduce((s, b) => s + b.quantity, 0);
    const totalAsk = asks.reduce((s, a) => s + a.quantity, 0);
    const total = totalBid + totalAsk;
    if (total > 0) {
      const imbalance = (totalBid - totalAsk) / total;
      const barY = h - padding.bottom + 8;
      const barH = 6;
      const barW = w - padding.left - padding.right;
      const midX = padding.left + barW / 2;

      ctx.fillStyle = 'rgba(255,255,255,0.04)';
      ctx.fillRect(padding.left, barY, barW, barH);

      const imbalanceW = Math.abs(imbalance) * (barW / 2);
      if (imbalance >= 0) {
        ctx.fillStyle = Math.abs(imbalance) > 0.3 ? 'rgba(255,23,68,0.6)' : 'rgba(255,23,68,0.3)';
        ctx.fillRect(midX, barY, imbalanceW, barH);
      } else {
        ctx.fillStyle = Math.abs(imbalance) > 0.3 ? 'rgba(0,200,83,0.6)' : 'rgba(0,200,83,0.3)';
        ctx.fillRect(midX - imbalanceW, barY, imbalanceW, barH);
      }

      ctx.font = '8px SF Mono, JetBrains Mono, monospace';
      ctx.fillStyle = 'rgba(255,255,255,0.25)';
      ctx.textAlign = 'left';
      ctx.fillText('BID', padding.left, barY + barH + 10);
      ctx.textAlign = 'right';
      ctx.fillText('ASK', padding.left + barW, barY + barH + 10);
      ctx.textAlign = 'center';
      ctx.fillStyle = Math.abs(imbalance) > 0.3 ? '#FF9F0A' : 'rgba(255,255,255,0.35)';
      ctx.fillText(`PRESSURE ${(imbalance * 100).toFixed(0)}%`, midX, barY + barH + 10);
    }
  }, [bids, asks]);

  const { ref } = useCanvas(draw, [bids, asks]);

  return (
    <canvas
      ref={ref}
      style={{ width: '100%', height: '100%', display: 'block' }}
    />
  );
});

const TradeQueue = memo(function TradeQueue({ trades }: { trades: TradeRecord[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', overflow: 'auto', flex: 1 }}>
      {trades.length === 0 ? (
        <EmptyState title="暂无成交" description="当前没有成交记录" size="sm" />
      ) : trades.map((trade) => {
        const isBuy = trade.direction === 'BUY';
        const isLarge = trade.amount > 1_000_000;
        return (
          <div
            key={trade.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 20px',
              borderBottom: '1px solid var(--separator)',
              borderLeft: isLarge ? '2px solid var(--accent)' : '2px solid transparent',
              transition: 'background var(--dur-fast) var(--ease-apple)',
              cursor: 'default',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-quaternary)', width: 52, fontVariantNumeric: 'tabular-nums' }}>
              {trade.time}
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: 'var(--r-xs)',
              background: isBuy ? 'var(--rise-bg)' : 'var(--fall-bg)',
              color: isBuy ? 'var(--signal-rise)' : 'var(--signal-fall)',
              width: 32,
              textAlign: 'center',
              letterSpacing: '0.04em',
            }}>
              {trade.direction}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: isBuy ? 'var(--signal-rise)' : 'var(--signal-fall)', fontVariantNumeric: 'tabular-nums', width: 64, textAlign: 'right' }}>
              {formatPrice(trade.price)}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums', width: 64, textAlign: 'right' }}>
              {formatVolume(trade.quantity)}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)', fontVariantNumeric: 'tabular-nums', flex: 1, textAlign: 'right' }}>
              {formatAmount(trade.amount)}
            </span>
          </div>
        );
      })}
    </div>
  );
});

const ExecutionQualityPanel = memo(function ExecutionQualityPanel() {
  const { stats, loading } = useExecutionStats();

  if (loading) {
    return (
      <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} style={{ background: 'var(--bg-overlay)', borderRadius: 'var(--r-md)', padding: '14px 16px', height: 60 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase', color: 'var(--label-tertiary)', letterSpacing: '0.06em', marginBottom: 6 }}>—</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, color: 'var(--label-quaternary)', fontWeight: 600 }}>—</div>
          </div>
        ))}
      </div>
    );
  }

  const metrics = stats ? [
    { label: 'SHARPE', value: stats.vwap.toFixed(2) },
    { label: 'TRADES', value: String(stats.twap) },
    { label: 'AVG WIN', value: `${stats.avgSlippage.toFixed(2)}` },
    { label: 'WIN RATE', value: `${stats.fillRate.toFixed(1)}%` },
  ] : [
    { label: 'SHARPE', value: '—' },
    { label: 'TRADES', value: '—' },
    { label: 'AVG WIN', value: '—' },
    { label: 'WIN RATE', value: '—' },
  ];

  return (
    <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
      {metrics.map((m) => (
        <div
          key={m.label}
          style={{
            background: 'var(--bg-overlay)',
            borderRadius: 'var(--r-md)',
            padding: '14px 16px',
          }}
        >
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase', color: 'var(--label-tertiary)', letterSpacing: '0.06em', marginBottom: 6 }}>
            {m.label}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, color: 'var(--label-primary)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
            {m.value}
          </div>
        </div>
      ))}
    </div>
  );
});

const ORDER_INPUT: React.CSSProperties = {
  width: '100%',
  height: 36,
  background: 'var(--bg-overlay)',
  border: '1px solid var(--separator)',
  borderRadius: 'var(--r-md)',
  color: 'var(--label-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: 13,
  padding: '0 12px',
  outline: 'none',
  boxSizing: 'border-box',
};

const QuickOrderPanel = memo(function QuickOrderPanel() {
  const [symbol, setSymbol] = useState('600519.SH');
  const [orderType, setOrderType] = useState<'limit' | 'market'>('limit');
  const [price, setPrice] = useState('12.50');
  const [quantity, setQuantity] = useState(0);
  const [showConfirm, setShowConfirm] = useState(false);
  const [direction, setDirection] = useState<'BUY' | 'SELL'>('BUY');
  const [sizeAck, setSizeAck] = useState(false);
  const killSwitchActive = useRiskStore(s => s.killSwitchActive);

  const totalAmount = orderType === 'limit' ? +price * quantity : 0;
  const changePct = 0;
  const SIZE_LIMIT = 5_000_000;

  const preTradeChecks = useMemo(() => {
    const checks: Array<{ id: string; level: 'block' | 'warn'; message: string }> = [];
    if (killSwitchActive) {
      checks.push({ id: 'kill', level: 'block', message: 'Kill switch active — all trading disabled' });
    }
    if (totalAmount > SIZE_LIMIT) {
      checks.push({ id: 'size', level: 'warn', message: `Single order exceeds ¥${(SIZE_LIMIT / 1e4).toFixed(0)}万 size limit` });
    }
    if (changePct > 9.8 && direction === 'BUY') {
      checks.push({ id: 'limitup', level: 'warn', message: 'Limit-up — fill unlikely' });
    }
    if (changePct < -9.8 && direction === 'SELL') {
      checks.push({ id: 'limitdown', level: 'warn', message: 'Limit-down — fill unlikely' });
    }
    return checks;
  }, [killSwitchActive, totalAmount, changePct, direction]);

  const hasBlock = preTradeChecks.some(c => c.level === 'block');
  const hasWarn = preTradeChecks.some(c => c.level === 'warn');

  const handleQuantityAdd = useCallback((delta: number) => {
    setQuantity((prev) => Math.max(0, prev + delta));
  }, []);

  const handleSubmit = useCallback(() => {
    if (hasBlock) return;
    setShowConfirm(true);
  }, [hasBlock, symbol, direction, quantity, price, preTradeChecks]);

  const handleConfirm = useCallback(() => {
    setShowConfirm(false);
    setQuantity(0);
    setSizeAck(false);
  }, []);

  const handleCancel = useCallback(() => {
    setShowConfirm(false);
    setSizeAck(false);
  }, []);

  return (
    <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <input
        style={ORDER_INPUT}
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="代码"
      />

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={() => setDirection('BUY')}
          style={{
            flex: 1,
            height: 32,
            background: direction === 'BUY' ? 'var(--rise-bg)' : 'var(--bg-overlay)',
            border: direction === 'BUY' ? '1px solid rgba(0,200,83,0.3)' : '1px solid var(--separator)',
            borderRadius: 'var(--r-md)',
            color: direction === 'BUY' ? 'var(--signal-rise)' : 'var(--label-tertiary)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all var(--dur-fast) var(--ease-apple)',
          }}
        >
          BUY
        </button>
        <button
          onClick={() => setDirection('SELL')}
          style={{
            flex: 1,
            height: 32,
            background: direction === 'SELL' ? 'var(--fall-bg)' : 'var(--bg-overlay)',
            border: direction === 'SELL' ? '1px solid rgba(255,23,68,0.3)' : '1px solid var(--separator)',
            borderRadius: 'var(--r-md)',
            color: direction === 'SELL' ? 'var(--signal-fall)' : 'var(--label-tertiary)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all var(--dur-fast) var(--ease-apple)',
          }}
        >
          SELL
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={() => setOrderType('limit')}
          style={{
            flex: 1,
            height: 32,
            background: orderType === 'limit' ? 'var(--accent-soft)' : 'var(--bg-overlay)',
            border: orderType === 'limit' ? '1px solid rgba(10,132,255,0.3)' : '1px solid var(--separator)',
            borderRadius: 'var(--r-md)',
            color: orderType === 'limit' ? 'var(--accent)' : 'var(--label-tertiary)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            cursor: 'pointer',
            transition: 'all var(--dur-fast) var(--ease-apple)',
          }}
        >
          限价
        </button>
        <button
          onClick={() => setOrderType('market')}
          style={{
            flex: 1,
            height: 32,
            background: orderType === 'market' ? 'var(--accent-soft)' : 'var(--bg-overlay)',
            border: orderType === 'market' ? '1px solid rgba(10,132,255,0.3)' : '1px solid var(--separator)',
            borderRadius: 'var(--r-md)',
            color: orderType === 'market' ? 'var(--accent)' : 'var(--label-tertiary)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            cursor: 'pointer',
            transition: 'all var(--dur-fast) var(--ease-apple)',
          }}
        >
          市价
        </button>
      </div>

      {orderType === 'limit' && (
        <input
          style={ORDER_INPUT}
          type="number"
          step="0.01"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          placeholder="价格"
        />
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          style={{ ...ORDER_INPUT, flex: 1 }}
          type="number"
          value={quantity || ''}
          onChange={(e) => setQuantity(Math.max(0, +e.target.value))}
          placeholder="数量"
        />
      </div>

      <div style={{ display: 'flex', gap: 6 }}>
        {[100, 1000, 10000].map((delta) => (
          <button
            key={delta}
            onClick={() => handleQuantityAdd(delta)}
            style={{
              flex: 1,
              height: 28,
              background: 'var(--bg-overlay)',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-xs)',
              color: 'var(--label-secondary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              cursor: 'pointer',
              transition: 'all var(--dur-fast) var(--ease-apple)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--accent)';
              e.currentTarget.style.color = 'var(--accent)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--separator)';
              e.currentTarget.style.color = 'var(--label-secondary)';
            }}
          >
            +{delta}
          </button>
        ))}
      </div>

      {orderType === 'limit' && quantity > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)' }}>合计金额</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--accent)', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
            {formatAmount(totalAmount)}
          </span>
        </div>
      )}

      {preTradeChecks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {preTradeChecks.map((check) => (
            <div
              key={check.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 12px',
                background: check.level === 'block' ? 'rgba(255,23,68,0.08)' : 'rgba(255,171,0,0.08)',
                border: `1px solid ${check.level === 'block' ? 'rgba(255,23,68,0.20)' : 'rgba(255,171,0,0.20)'}`,
                borderRadius: 'var(--r-md)',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: check.level === 'block' ? '#FF1744' : '#FFAB00',
              }}
            >
              <span style={{ fontWeight: 700, letterSpacing: '0.04em' }}>
                {check.level === 'block' ? '⛔' : '⚠️'}
              </span>
              {check.message}
            </div>
          ))}
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={hasBlock}
        style={{
          width: '100%',
          height: 44,
          background: hasBlock ? 'rgba(255,255,255,0.06)' : 'var(--accent)',
          border: 'none',
          borderRadius: 'var(--r-md)',
          color: hasBlock ? 'var(--label-quaternary)' : '#FFFFFF',
          fontFamily: 'var(--font-sans)',
          fontSize: 14,
          fontWeight: 600,
          cursor: hasBlock ? 'not-allowed' : 'pointer',
          letterSpacing: '0.02em',
          opacity: hasBlock ? 0.5 : 1,
          transition: 'opacity var(--dur-fast) var(--ease-apple)',
        }}
        onMouseEnter={(e) => { if (!hasBlock) e.currentTarget.style.opacity = '0.85'; }}
        onMouseLeave={(e) => { if (!hasBlock) e.currentTarget.style.opacity = '1'; }}
      >
        {hasBlock ? 'BLOCKED' : 'SUBMIT'}
      </button>

      {showConfirm && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.6)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={handleCancel}
        >
          <div
            style={{
              background: 'var(--bg-elevated)',
              border: '1px solid var(--separator-hi)',
              borderRadius: 'var(--r-xl)',
              padding: '32px 40px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 24,
              boxShadow: 'var(--shadow-lg)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: 18, color: 'var(--label-primary)', fontWeight: 600 }}>
              确认下单？
            </span>
            {hasWarn && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
                {preTradeChecks.filter(c => c.level === 'warn').map(check => (
                  <div key={check.id} style={{
                    padding: '8px 12px',
                    background: 'rgba(255,171,0,0.08)',
                    border: '1px solid rgba(255,171,0,0.20)',
                    borderRadius: 'var(--r-md)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: '#FFAB00',
                  }}>
                    ⚠️ {check.message}
                  </div>
                ))}
                {totalAmount > SIZE_LIMIT && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', userSelect: 'none' }}>
                    <input
                      type="checkbox"
                      checked={sizeAck}
                      onChange={e => setSizeAck(e.target.checked)}
                      style={{ accentColor: 'var(--accent)' }}
                    />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-secondary)' }}>
                      I acknowledge the size risk
                    </span>
                  </label>
                )}
              </div>
            )}
            <div style={{ display: 'flex', gap: 16 }}>
              <button
                onClick={handleConfirm}
                disabled={hasWarn && !sizeAck}
                style={{
                  width: 100,
                  height: 40,
                  background: (hasWarn && !sizeAck) ? 'rgba(255,255,255,0.06)' : 'var(--accent)',
                  border: 'none',
                  borderRadius: 'var(--r-md)',
                  color: (hasWarn && !sizeAck) ? 'var(--label-quaternary)' : '#FFFFFF',
                  fontFamily: 'var(--font-sans)',
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: (hasWarn && !sizeAck) ? 'not-allowed' : 'pointer',
                  transition: 'opacity var(--dur-fast) var(--ease-apple)',
                }}
              >
                CONFIRM
              </button>
              <button
                onClick={handleCancel}
                style={{
                  width: 100,
                  height: 40,
                  background: 'transparent',
                  border: '1px solid var(--separator-hi)',
                  borderRadius: 'var(--r-md)',
                  color: 'var(--label-secondary)',
                  fontFamily: 'var(--font-sans)',
                  fontSize: 13,
                  cursor: 'pointer',
                  transition: 'all var(--dur-fast) var(--ease-apple)',
                }}
              >
                CANCEL
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

const KillSwitchPanel = memo(function KillSwitchPanel() {
  const killSwitchActive = useRiskStore(s => s.killSwitchActive);
  const triggerKillSwitch = useRiskStore(s => s.triggerKillSwitch);
  const resetKillSwitch = useRiskStore(s => s.resetKillSwitch);
  const [showDialog, setShowDialog] = useState(false);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const handleActivate = useCallback(async () => {
    if (!reason.trim()) return;
    setSubmitting(true);
    setFeedback(null);
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const data = await apiPost<{ message: string; closed_positions: number }>(
        '/trading/kill-switch',
        { reason: reason.trim() },
      );
      if (ac.signal.aborted) return;
      triggerKillSwitch();
      setFeedback({ ok: true, msg: `${data.message} (${data.closed_positions} positions closed)` });
      setShowDialog(false);
      setReason('');
    } catch (e) {
      if (ac.signal.aborted) return;
      setFeedback({ ok: false, msg: (e as Error).message || 'Kill switch failed' });
    } finally {
      if (!ac.signal.aborted) setSubmitting(false);
    }
  }, [reason, triggerKillSwitch]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    setShowDialog(false);
    setReason('');
    setSubmitting(false);
    setFeedback(null);
  }, []);

  const handleDeactivate = useCallback(() => {
    resetKillSwitch();
    setFeedback(null);
  }, [resetKillSwitch]);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  if (killSwitchActive) {
    return (
      <div
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 10000,
          background: 'rgba(255,23,68,0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 48,
            fontWeight: 700,
            color: '#FF1744',
            letterSpacing: '0.04em',
          }}
        >
          KILL SWITCH ACTIVE
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            color: 'rgba(255,255,255,0.55)',
          }}
        >
          All trading operations suspended
        </span>
        <button
          onClick={handleDeactivate}
          style={{
            marginTop: 16,
            padding: '8px 24px',
            background: 'rgba(255,255,255,0.06)',
            color: '#ffffff',
            border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: 'var(--r-md)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            cursor: 'pointer',
            transition: 'background var(--dur-fast) var(--ease-apple)',
          }}
        >
          DEACTIVATE
        </button>
      </div>
    );
  }

  return (
    <>
      <button
        onClick={() => setShowDialog(true)}
        style={{
          padding: '6px 16px',
          background: 'rgba(255,23,68,0.10)',
          color: '#FF1744',
          border: '1px solid rgba(255,23,68,0.20)',
          borderRadius: 'var(--r-xs)',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.06em',
          cursor: 'pointer',
          transition: 'background var(--dur-fast) var(--ease-apple)',
          whiteSpace: 'nowrap',
        }}
      >
        KILL SWITCH
      </button>

      {showDialog && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.60)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10000,
          }}
          onClick={handleCancel}
        >
          <div
            style={{
              background: '#1a1a1a',
              border: '1px solid rgba(255,23,68,0.30)',
              borderRadius: 'var(--r-xl)',
              padding: '32px 40px',
              display: 'flex',
              flexDirection: 'column',
              gap: 20,
              minWidth: 380,
              boxShadow: '0 24px 80px rgba(255,23,68,0.12)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 16, color: '#FF1744', fontWeight: 700, letterSpacing: '0.04em' }}>
              ACTIVATE KILL SWITCH
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.50)' }}>
              This will immediately close all positions and suspend trading.
            </span>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for activation"
              disabled={submitting}
              style={{
                width: '100%',
                height: 36,
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,23,68,0.20)',
                borderRadius: 'var(--r-md)',
                color: '#ffffff',
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                padding: '0 12px',
                outline: 'none',
                boxSizing: 'border-box',
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !submitting && reason.trim()) handleActivate();
                if (e.key === 'Escape') handleCancel();
              }}
              autoFocus
            />
            {feedback && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: feedback.ok ? '#00C853' : '#FF1744',
                }}
              >
                {feedback.msg}
              </span>
            )}
            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button
                onClick={handleCancel}
                disabled={submitting}
                style={{
                  padding: '8px 20px',
                  background: 'transparent',
                  border: '1px solid rgba(255,255,255,0.12)',
                  borderRadius: 'var(--r-md)',
                  color: 'rgba(255,255,255,0.55)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  opacity: submitting ? 0.5 : 1,
                }}
              >
                CANCEL
              </button>
              <button
                onClick={handleActivate}
                disabled={submitting || !reason.trim()}
                style={{
                  padding: '8px 20px',
                  background: '#FF1744',
                  border: 'none',
                  borderRadius: 'var(--r-md)',
                  color: '#ffffff',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: submitting || !reason.trim() ? 'not-allowed' : 'pointer',
                  opacity: submitting || !reason.trim() ? 0.5 : 1,
                  transition: 'opacity var(--dur-fast) var(--ease-apple)',
                }}
              >
                {submitting ? 'EXECUTING...' : 'EXECUTE'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
});

export function TerminalPage() {
  const orderBook = useTerminalStore(s => s.orderBook);
  const selectedSymbol = useTerminalStore(s => s.selectedSymbol);
  const fetchOrderBook = useTerminalStore(s => s.fetchOrderBook);
  const { data: tradesData, isLoading: tradesLoading, error: tradesError, refetch: refetchTrades } = useTradingHistory();
  const { pnlData, connected: pnlConnected, refresh: refreshPnL } = usePnLWebSocket([]);

  const trades: TradeRecord[] = useMemo(() => {
    if (!tradesData?.trades) return [];
    return tradesData.trades.map((t) => ({
      id: t.id,
      price: t.price,
      quantity: t.shares,
      amount: t.amount,
      direction: t.action.toUpperCase() === 'SELL' ? 'SELL' as const : 'BUY' as const,
      time: t.timestamp,
    })).slice(0, 50);
  }, [tradesData]);

  useEffect(() => {
    const sym = selectedSymbol || '000001.SZ';
    fetchOrderBook(sym);
  }, [selectedSymbol, fetchOrderBook]);

  return (
    <div style={{ background: 'var(--bg-base)', minHeight: '100%', padding: 24, boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 18, fontWeight: 600, color: 'var(--label-primary)' }}>
            Terminal
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)', letterSpacing: '0.04em' }}>
            {selectedSymbol || '000001.SZ'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={refreshPnL}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              background: 'transparent',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-xs)',
              color: 'var(--label-tertiary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              cursor: 'pointer',
              transition: 'all var(--dur-fast) var(--ease-apple)',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--accent)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--separator)'; e.currentTarget.style.color = 'var(--label-tertiary)'; }}
          >
            <span style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: pnlConnected ? '#00C853' : '#FF1744',
              transition: 'background var(--dur-fast) var(--ease-apple)',
            }} />
            PnL
          </button>
          {pnlData && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontVariantNumeric: 'tabular-nums', color: pnlData.summary.total_pnl >= 0 ? 'var(--signal-rise)' : 'var(--signal-fall)' }}>
              {pnlData.summary.total_pnl >= 0 ? '+' : ''}{pnlData.summary.total_pnl.toFixed(2)}
            </span>
          )}
          <KillSwitchPanel />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 48px - 52px - 56px)' }}>
        <div style={{ width: '60%', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ ...panelStyle, height: 320, display: 'flex', flexDirection: 'column' }}>
            <div style={panelTitleStyle}>委托簿</div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <ErrorBoundary fallback={<div style={{ color: 'var(--label-tertiary)', padding: 16 }}>Chart unavailable</div>}>
                <OrderBookCanvas bids={orderBook.bids} asks={orderBook.asks} />
              </ErrorBoundary>
            </div>
          </div>

          <div style={{ ...panelStyle, height: 140 }}>
            <div style={panelTitleStyle}>深度图</div>
            <div style={{ padding: '8px 12px' }}>
              <ErrorBoundary fallback={<div style={{ color: 'var(--label-tertiary)', padding: 16 }}>Chart unavailable</div>}>
                <DepthChart bids={orderBook.bids} asks={orderBook.asks} height={100} />
              </ErrorBoundary>
            </div>
          </div>

          <div style={{ ...panelStyle, flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={panelTitleStyle}>成交队列</div>
            {tradesLoading ? (
              <SkeletonCard rows={4} />
            ) : tradesError ? (
              <EmptyState title="成交数据加载失败" description="请检查网络连接或稍后重试" size="sm" action={{ label: '重试', onClick: () => refetchTrades() }} />
            ) : (
              <TradeQueue trades={trades} />
            )}
          </div>
        </div>

        <div style={{ width: '40%', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={panelStyle}>
            <div style={panelTitleStyle}>执行质量</div>
            <ExecutionQualityPanel />
          </div>

          <div style={{ ...panelStyle, flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div style={panelTitleStyle}>快捷下单</div>
            <QuickOrderPanel />
          </div>
        </div>
      </div>
    </div>
  );
}
