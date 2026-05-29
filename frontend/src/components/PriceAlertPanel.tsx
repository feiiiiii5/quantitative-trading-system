import { useState, useCallback, useEffect, useRef, memo, useOptimistic } from 'react';
import { formatPrice } from '@/utils/format';
import { useToastStore } from '@/stores/toast';
import { useMarketStore } from '@/stores/market';
import { colors } from '@/design/tokens/colors';

interface PriceAlert {
  id: string;
  symbol: string;
  condition: 'above' | 'below' | 'change_up' | 'change_down' | 'volume_spike';
  threshold: number;
  active: boolean;
  triggered?: { price: number; time: string };
  notify: Array<'toast' | 'sound' | 'browser'>;
}

interface TriggeredLogEntry {
  alertId: string;
  symbol: string;
  condition: PriceAlert['condition'];
  threshold: number;
  triggerPrice: number;
  triggerTime: string;
}

const STORAGE_KEY = 'qc_price_alerts';
const HISTORY_KEY = 'qc_alert_history';
const MAX_HISTORY = 50;

function loadAlerts(): PriceAlert[] {
  try { const raw = localStorage.getItem(STORAGE_KEY); return raw ? JSON.parse(raw) : []; } catch { return []; }
}

function saveAlerts(alerts: PriceAlert[]): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(alerts)); } catch {}
}

function loadHistory(): TriggeredLogEntry[] {
  try { const raw = localStorage.getItem(HISTORY_KEY); return raw ? JSON.parse(raw) : []; } catch { return []; }
}

function saveHistory(entries: TriggeredLogEntry[]): void {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY))); } catch {}
}

const CONDITION_LABELS: Record<PriceAlert['condition'], string> = {
  above: '价格高于',
  below: '价格低于',
  change_up: '涨幅超过',
  change_down: '跌幅超过',
  volume_spike: '成交量异动',
};

export const PriceAlertPanel = memo(function PriceAlertPanel() {
  const [alerts, setAlerts] = useState<PriceAlert[]>(loadAlerts);
  const [history, setHistory] = useState<TriggeredLogEntry[]>(loadHistory);
  const [optimisticHistory, addOptimisticEntry] = useOptimistic(
    history,
    (state, newEntry: TriggeredLogEntry) => [newEntry, ...state].slice(0, MAX_HISTORY),
  );
  const [symbol, setSymbol] = useState('');
  const [condition, setCondition] = useState<PriceAlert['condition']>('above');
  const [threshold, setThreshold] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const addToast = useToastStore(s => s.addToast);

  useEffect(() => { saveAlerts(alerts); }, [alerts]);
  useEffect(() => { saveHistory(history); }, [history]);

  const triggeredRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const activeAlerts = alerts.filter(a => a.active && !a.triggered);
    if (activeAlerts.length === 0) return;

    const stocks = useMarketStore.getState().stocks;
    let changed = false;
    const updated = alerts.map(alert => {
      if (!alert.active || alert.triggered || triggeredRef.current.has(alert.id)) return alert;
      const stock = stocks[alert.symbol];
      if (!stock || !stock.price) return alert;
      const price = stock.price;
      const triggered =
        (alert.condition === 'above' && price >= alert.threshold) ||
        (alert.condition === 'below' && price <= alert.threshold) ||
        (alert.condition === 'change_up' && stock.change_pct >= alert.threshold) ||
        (alert.condition === 'change_down' && stock.change_pct <= -alert.threshold) ||
        (alert.condition === 'volume_spike' && stock.volume >= alert.threshold);
      if (triggered) {
        triggeredRef.current.add(alert.id);
        changed = true;
        const triggerTime = new Date().toLocaleTimeString();
        addToast({
          type: 'info',
          title: '价格预警触发',
          body: `${alert.symbol} ${CONDITION_LABELS[alert.condition]} ${alert.threshold}，当前价 ${formatPrice(price)}`,
          duration: 8000,
        });
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification(`${alert.symbol} 预警触发`, { body: `${CONDITION_LABELS[alert.condition]} ${alert.threshold}` });
        }
        addOptimisticEntry({
          alertId: alert.id,
          symbol: alert.symbol,
          condition: alert.condition,
          threshold: alert.threshold,
          triggerPrice: price,
          triggerTime,
        });
        setHistory(prev => [{
          alertId: alert.id,
          symbol: alert.symbol,
          condition: alert.condition,
          threshold: alert.threshold,
          triggerPrice: price,
          triggerTime,
        }, ...prev].slice(0, MAX_HISTORY));
        return { ...alert, triggered: { price, time: triggerTime } };
      }
      return alert;
    });
    if (changed) setAlerts(updated);
  }, [alerts, addToast]);

  const requestNotificationPermission = useCallback(async () => {
    if ('Notification' in window && Notification.permission === 'default') {
      await Notification.requestPermission();
    }
  }, []);

  const addAlert = useCallback(() => {
    if (!symbol.trim() || !threshold) return;
    const numThreshold = parseFloat(threshold);
    if (!Number.isFinite(numThreshold) || numThreshold <= 0) return;
    const newAlert: PriceAlert = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      symbol: symbol.trim().toUpperCase(),
      condition,
      threshold: numThreshold,
      active: true,
      notify: ['toast', 'sound'],
    };
    setAlerts(prev => [...prev, newAlert]);
    setSymbol('');
    setThreshold('');
    addToast({ type: 'info', title: '预警已创建', body: `${newAlert.symbol} ${CONDITION_LABELS[condition]} ${threshold}`, duration: 3000 });
  }, [symbol, condition, threshold, addToast]);

  const removeAlert = useCallback((id: string) => {
    setAlerts(prev => prev.filter(a => a.id !== id));
  }, []);

  const toggleAlert = useCallback((id: string) => {
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, active: !a.active } : a));
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          value={symbol}
          onChange={e => setSymbol(e.target.value)}
          placeholder="股票代码"
          style={{ width: 100, background: 'var(--bg-overlay)', border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)', padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--label-primary)', outline: 'none' }}
        />
        <select
          value={condition}
          onChange={e => setCondition(e.target.value as PriceAlert['condition'])}
          style={{ background: 'var(--bg-overlay)', border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)', padding: '6px 10px', fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--label-primary)', outline: 'none' }}
        >
          {Object.entries(CONDITION_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        <input
          value={threshold}
          onChange={e => setThreshold(e.target.value)}
          placeholder="阈值"
          type="number"
          style={{ width: 80, background: 'var(--bg-overlay)', border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)', padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--label-primary)', outline: 'none' }}
        />
        <button
          onClick={addAlert}
          style={{ background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 'var(--r-sm)', padding: '6px 14px', fontFamily: 'var(--font-mono)', fontSize: 12, cursor: 'pointer' }}
        >
          添加
        </button>
        <button
          onClick={requestNotificationPermission}
          style={{ background: 'transparent', color: 'var(--label-tertiary)', border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)', padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer' }}
        >
          🔔 通知权限
        </button>
      </div>

      {alerts.length === 0 && !showHistory && (
        <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--label-quaternary)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
          NO ALERTS SET
        </div>
      )}

      {!showHistory && alerts.map(alert => (
        <div
          key={alert.id}
          style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
            background: alert.active ? 'var(--bg-overlay)' : 'transparent',
            border: '1px solid var(--separator)', borderRadius: 'var(--r-md)',
            opacity: alert.active ? 1 : 0.5,
          }}
        >
          <span
            onClick={() => toggleAlert(alert.id)}
            style={{ width: 8, height: 8, borderRadius: '50%', background: alert.active ? colors.accent.success : 'var(--label-quaternary)', cursor: 'pointer', flexShrink: 0 }}
          />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--accent)', width: 72 }}>{alert.symbol}</span>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--label-secondary)' }}>{CONDITION_LABELS[alert.condition]}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: colors.market.rise, fontVariantNumeric: 'tabular-nums' }}>{formatPrice(alert.threshold)}</span>
          {alert.triggered && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--orange)' }}>
              TRIGGERED @ {alert.triggered.price}
            </span>
          )}
          <span style={{ flex: 1 }} />
          <button
            onClick={() => removeAlert(alert.id)}
            style={{ background: 'transparent', border: 'none', color: 'var(--label-quaternary)', cursor: 'pointer', fontSize: 14, padding: '0 4px' }}
          >
            ×
          </button>
        </div>
      ))}

      <div style={{ display: 'flex', justifyContent: 'center', borderTop: '1px solid var(--separator)', paddingTop: 8, marginTop: 4 }}>
        <button
          onClick={() => setShowHistory(v => !v)}
          style={{ background: 'transparent', border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)', padding: '4px 12px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', cursor: 'pointer' }}
        >
          {showHistory ? '← 返回预警列表' : `📋 触发历史 (${optimisticHistory.length})`}
        </button>
      </div>

      {showHistory && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 240, overflowY: 'auto' }}>
          {optimisticHistory.length === 0 && (
            <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--label-quaternary)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              NO TRIGGERED HISTORY
            </div>
          )}
          {optimisticHistory.map((entry, i) => (
            <div
              key={`${entry.alertId}-${i}`}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px', background: 'var(--bg-overlay)', borderRadius: 'var(--r-sm)', fontSize: 11 }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent)', width: 64 }}>{entry.symbol}</span>
              <span style={{ fontFamily: 'var(--font-sans)', color: 'var(--label-tertiary)' }}>{CONDITION_LABELS[entry.condition]}</span>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--signal-rise)', fontVariantNumeric: 'tabular-nums' }}>{formatPrice(entry.threshold)}</span>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--label-quaternary)' }}>→</span>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--orange)', fontVariantNumeric: 'tabular-nums' }}>{formatPrice(entry.triggerPrice)}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-quaternary)' }}>{entry.triggerTime}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});
