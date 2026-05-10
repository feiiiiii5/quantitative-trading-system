import { useState, useCallback, useEffect, memo } from 'react';
import { useCanvas } from '@/hooks/useCanvas';
import { useTerminalStore } from '@/stores/terminal';
import { formatPrice, formatVolume, formatAmount } from '@/utils/format';
import type { OrderBookEntry, TradeRecord } from '@/types';

const GOLD = '#C9A96E';
const BID_COLOR = '#4E9E6E';
const ASK_COLOR = '#D4584A';
const MONO = "'JetBrains Mono', monospace";
const SERIF = "'Cormorant Garamond', serif";

const panelStyle: React.CSSProperties = {
  background: '#0a0a0a',
  borderRadius: '8px',
  border: '1px solid rgba(255,255,255,0.04)',
  boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
  overflow: 'hidden',
};

const panelTitleStyle: React.CSSProperties = {
  fontFamily: SERIF,
  fontSize: '18px',
  color: GOLD,
  fontWeight: 500,
  padding: '16px 20px',
  borderBottom: '1px solid rgba(255,255,255,0.04)',
};

const MOCK_EXECUTION_STATS = { vwap: 12.48, twap: 12.45, avgSlippage: 0.03, fillRate: 94.2 };

const OrderBookCanvas = memo(function OrderBookCanvas({ bids, asks }: { bids: OrderBookEntry[]; asks: OrderBookEntry[] }) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    ctx.clearRect(0, 0, w, h);
    if (bids.length === 0 && asks.length === 0) {
      ctx.font = `11px ${MONO}`;
      ctx.fillStyle = 'rgba(255,255,255,0.2)';
      ctx.textAlign = 'center';
      ctx.fillText('NO DATA', w / 2, h / 2);
      return;
    }
    const maxQty = Math.max(
      ...bids.map((b) => b.quantity),
      ...asks.map((b) => b.quantity),
      1,
    );
    const padding = { left: 72, right: 64, top: 8, bottom: 8 };
    const rowHeight = (h - padding.top - padding.bottom - 22) / 20;
    const barMaxWidth = w - padding.left - padding.right;

    for (let i = 0; i < 10; i++) {
      const y = padding.top + i * rowHeight;
      const ask = asks[i];
      if (!ask) continue;
      const barW = (ask.quantity / maxQty) * barMaxWidth;

      ctx.fillStyle = 'rgba(212,88,74,0.18)';
      ctx.fillRect(padding.left, y, barW, rowHeight - 2);

      ctx.font = `11px ${MONO}`;
      ctx.fillStyle = ASK_COLOR;
      ctx.textAlign = 'right';
      ctx.fillText(formatPrice(ask.price), padding.left - 8, y + rowHeight * 0.72);
      ctx.textAlign = 'left';
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.fillText(String(ask.quantity), padding.left + barW + 6, y + rowHeight * 0.72);
    }

    const spreadY = padding.top + 10 * rowHeight;
    ctx.font = `10px ${MONO}`;
    ctx.fillStyle = GOLD;
    ctx.textAlign = 'center';
    const firstAsk = asks[0];
    const firstBid = bids[0];
    if (firstAsk && firstBid) {
      const spread = firstAsk.price - firstBid.price;
      const midPrice = (firstAsk.price + firstBid.price) / 2;
      const spreadPct = midPrice !== 0 ? ((spread / midPrice) * 100).toFixed(2) : '0.00';
      ctx.fillText(`SPREAD: ${spread.toFixed(2)} (${spreadPct}%)`, w / 2, spreadY + 14);
    }

    for (let i = 0; i < 10; i++) {
      const y = spreadY + 22 + i * rowHeight;
      const bid = bids[i];
      if (!bid) continue;
      const barW = (bid.quantity / maxQty) * barMaxWidth;

      ctx.fillStyle = 'rgba(78,158,110,0.18)';
      ctx.fillRect(padding.left, y, barW, rowHeight - 2);

      ctx.font = `11px ${MONO}`;
      ctx.fillStyle = BID_COLOR;
      ctx.textAlign = 'right';
      ctx.fillText(formatPrice(bid.price), padding.left - 8, y + rowHeight * 0.72);
      ctx.textAlign = 'left';
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.fillText(String(bid.quantity), padding.left + barW + 6, y + rowHeight * 0.72);
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
        <div style={{ padding: '32px 20px', textAlign: 'center', fontFamily: MONO, fontSize: '11px', color: 'rgba(255,255,255,0.2)', letterSpacing: '0.06em' }}>NO TRADES</div>
      ) : trades.map((trade) => {
        const isBuy = trade.direction === 'BUY';
        const isLarge = trade.amount > 1_000_000;
        return (
          <div
            key={trade.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '6px 20px',
              borderBottom: '1px solid rgba(255,255,255,0.03)',
              borderLeft: isLarge ? `2px solid ${GOLD}` : '2px solid transparent',
              transition: 'background 80ms ease-out',
              cursor: 'default',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{ fontFamily: MONO, fontSize: '10px', color: 'rgba(255,255,255,0.3)', width: '52px', fontVariantNumeric: 'tabular-nums' }}>
              {trade.time}
            </span>
            <span style={{
              fontFamily: MONO,
              fontSize: '9px',
              fontWeight: 600,
              padding: '1px 6px',
              borderRadius: '2px',
              background: isBuy ? 'rgba(212,88,74,0.15)' : 'rgba(78,158,110,0.15)',
              color: isBuy ? ASK_COLOR : BID_COLOR,
              width: '32px',
              textAlign: 'center',
              letterSpacing: '0.04em',
            }}>
              {trade.direction}
            </span>
            <span style={{ fontFamily: MONO, fontSize: '12px', color: isBuy ? ASK_COLOR : BID_COLOR, fontVariantNumeric: 'tabular-nums', width: '64px', textAlign: 'right' }}>
              {formatPrice(trade.price)}
            </span>
            <span style={{ fontFamily: MONO, fontSize: '11px', color: 'rgba(255,255,255,0.45)', fontVariantNumeric: 'tabular-nums', width: '64px', textAlign: 'right' }}>
              {formatVolume(trade.quantity)}
            </span>
            <span style={{ fontFamily: MONO, fontSize: '11px', color: 'rgba(255,255,255,0.35)', fontVariantNumeric: 'tabular-nums', flex: 1, textAlign: 'right' }}>
              {formatAmount(trade.amount)}
            </span>
          </div>
        );
      })}
    </div>
  );
});

const ExecutionQualityPanel = memo(function ExecutionQualityPanel() {
  const stats = MOCK_EXECUTION_STATS;
  const metrics = [
    { label: 'VWAP', value: formatPrice(stats.vwap) },
    { label: 'TWAP', value: formatPrice(stats.twap) },
    { label: 'AVG SLIPPAGE', value: `${stats.avgSlippage.toFixed(2)}%` },
    { label: 'FILL RATE', value: `${stats.fillRate.toFixed(1)}%` },
  ];

  return (
    <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
      {metrics.map((m) => (
        <div
          key={m.label}
          style={{
            background: '#0f0f0f',
            borderRadius: '6px',
            padding: '12px 16px',
          }}
        >
          <div style={{ fontFamily: MONO, fontSize: '9px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', letterSpacing: '0.06em', marginBottom: '6px' }}>
            {m.label}
          </div>
          <div style={{ fontFamily: MONO, fontSize: '18px', color: 'rgba(255,255,255,0.9)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
            {m.value}
          </div>
        </div>
      ))}
    </div>
  );
});

const QuickOrderPanel = memo(function QuickOrderPanel() {
  const [symbol, setSymbol] = useState('600519.SH');
  const [orderType, setOrderType] = useState<'limit' | 'market'>('limit');
  const [price, setPrice] = useState('12.50');
  const [quantity, setQuantity] = useState(0);
  const [showConfirm, setShowConfirm] = useState(false);

  const totalAmount = orderType === 'limit' ? +price * quantity : 0;

  const handleQuantityAdd = useCallback((delta: number) => {
    setQuantity((prev) => Math.max(0, prev + delta));
  }, []);

  const handleSubmit = useCallback(() => {
    setShowConfirm(true);
  }, []);

  const handleConfirm = useCallback(() => {
    setShowConfirm(false);
    setQuantity(0);
  }, []);

  const handleCancel = useCallback(() => {
    setShowConfirm(false);
  }, []);

  const inputStyle: React.CSSProperties = {
    width: '100%',
    height: '36px',
    background: '#0f0f0f',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '6px',
    color: 'rgba(255,255,255,0.9)',
    fontFamily: MONO,
    fontSize: '13px',
    padding: '0 12px',
    outline: 'none',
    boxSizing: 'border-box',
  };

  return (
    <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <input
        style={inputStyle}
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="代码"
      />

      <div style={{ display: 'flex', gap: '8px' }}>
        <button
          onClick={() => setOrderType('limit')}
          style={{
            flex: 1,
            height: '32px',
            background: orderType === 'limit' ? 'transparent' : '#0f0f0f',
            border: orderType === 'limit' ? `1px solid ${GOLD}` : '1px solid rgba(255,255,255,0.08)',
            borderRadius: '6px',
            color: orderType === 'limit' ? GOLD : 'rgba(255,255,255,0.4)',
            fontFamily: MONO,
            fontSize: '12px',
            cursor: 'pointer',
            transition: 'all 120ms ease-out',
          }}
        >
          限价
        </button>
        <button
          onClick={() => setOrderType('market')}
          style={{
            flex: 1,
            height: '32px',
            background: orderType === 'market' ? 'transparent' : '#0f0f0f',
            border: orderType === 'market' ? `1px solid ${GOLD}` : '1px solid rgba(255,255,255,0.08)',
            borderRadius: '6px',
            color: orderType === 'market' ? GOLD : 'rgba(255,255,255,0.4)',
            fontFamily: MONO,
            fontSize: '12px',
            cursor: 'pointer',
            transition: 'all 120ms ease-out',
          }}
        >
          市价
        </button>
      </div>

      {orderType === 'limit' && (
        <input
          style={inputStyle}
          type="number"
          step="0.01"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          placeholder="价格"
        />
      )}

      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
        <input
          style={{ ...inputStyle, flex: 1 }}
          type="number"
          value={quantity || ''}
          onChange={(e) => setQuantity(Math.max(0, +e.target.value))}
          placeholder="数量"
        />
      </div>

      <div style={{ display: 'flex', gap: '6px' }}>
        {[100, 1000, 10000].map((delta) => (
          <button
            key={delta}
            onClick={() => handleQuantityAdd(delta)}
            style={{
              flex: 1,
              height: '28px',
              background: '#0f0f0f',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: '4px',
              color: 'rgba(255,255,255,0.5)',
              fontFamily: MONO,
              fontSize: '11px',
              cursor: 'pointer',
              transition: 'all 80ms ease-out',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = GOLD;
              e.currentTarget.style.color = GOLD;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
              e.currentTarget.style.color = 'rgba(255,255,255,0.5)';
            }}
          >
            +{delta}
          </button>
        ))}
      </div>

      {orderType === 'limit' && quantity > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
          <span style={{ fontFamily: MONO, fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>合计金额</span>
          <span style={{ fontFamily: MONO, fontSize: '13px', color: GOLD, fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
            {formatAmount(totalAmount)}
          </span>
        </div>
      )}

      <button
        onClick={handleSubmit}
        style={{
          width: '100%',
          height: '44px',
          background: GOLD,
          border: 'none',
          borderRadius: '6px',
          color: '#000000',
          fontFamily: MONO,
          fontSize: '14px',
          fontWeight: 600,
          cursor: 'pointer',
          letterSpacing: '0.04em',
          transition: 'opacity 120ms ease-out',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.opacity = '0.85'; }}
        onMouseLeave={(e) => { e.currentTarget.style.opacity = '1'; }}
      >
        SUBMIT
      </button>

      {showConfirm && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={handleCancel}
        >
          <div
            style={{
              background: '#0a0a0a',
              border: `1px solid ${GOLD}`,
              borderRadius: '8px',
              padding: '32px 40px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '24px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <span style={{ fontFamily: SERIF, fontSize: '20px', color: GOLD, fontWeight: 500 }}>
              确认下单？
            </span>
            <div style={{ display: 'flex', gap: '16px' }}>
              <button
                onClick={handleConfirm}
                style={{
                  width: '100px',
                  height: '40px',
                  background: GOLD,
                  border: 'none',
                  borderRadius: '6px',
                  color: '#000000',
                  fontFamily: MONO,
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                CONFIRM
              </button>
              <button
                onClick={handleCancel}
                style={{
                  width: '100px',
                  height: '40px',
                  background: 'transparent',
                  border: '1px solid rgba(255,255,255,0.15)',
                  borderRadius: '6px',
                  color: 'rgba(255,255,255,0.6)',
                  fontFamily: MONO,
                  fontSize: '13px',
                  cursor: 'pointer',
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

export function TerminalPage() {
  const { orderBook, trades, selectedSymbol, fetchOrderBook, fetchTrades } = useTerminalStore();

  useEffect(() => {
    const sym = selectedSymbol || '000001.SZ';
    fetchOrderBook(sym);
    fetchTrades(sym);
  }, [selectedSymbol, fetchOrderBook, fetchTrades]);

  return (
    <div style={{ background: '#000000', minHeight: '100%', padding: '24px', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', gap: '16px', height: 'calc(100vh - 48px - 52px)' }}>
        <div style={{ width: '60%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ ...panelStyle, height: '320px', display: 'flex', flexDirection: 'column' }}>
            <div style={panelTitleStyle}>委托簿</div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <OrderBookCanvas bids={orderBook.bids} asks={orderBook.asks} />
            </div>
          </div>

          <div style={{ ...panelStyle, flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={panelTitleStyle}>成交队列</div>
            <TradeQueue trades={trades} />
          </div>
        </div>

        <div style={{ width: '40%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
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
