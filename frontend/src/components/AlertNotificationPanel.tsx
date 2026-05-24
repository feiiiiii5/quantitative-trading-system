import { useState, useCallback, memo } from 'react';
import { apiGet } from '@/api/client';
import { apiPost } from '@/api/client';

interface AlertItem {
  id: string;
  type: string;
  severity: 'info' | 'warning' | 'critical';
  title: string;
  message: string;
  symbol?: string;
  timestamp: number;
  acknowledged: boolean;
}

interface AlertNotificationPanelProps {
  open: boolean;
  onClose: () => void;
}

const SEVERITY_COLORS: Record<string, { bg: string; border: string; icon: string }> = {
  critical: { bg: 'var(--red-soft)', border: 'var(--red)', icon: '🔴' },
  warning: { bg: 'var(--orange-soft)', border: 'var(--orange)', icon: '🟡' },
  info: { bg: 'var(--accent-soft)', border: 'var(--accent)', icon: '🔵' },
};

export const AlertNotificationPanel = memo(function AlertNotificationPanel({ open, onClose }: AlertNotificationPanelProps) {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<AlertItem[]>('/alerts');
      setAlerts(Array.isArray(data) ? data : []);
    } catch {
      setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const acknowledgeAlert = useCallback(async (alertId: string) => {
    try {
      await apiPost(`/alerts/${alertId}/acknowledge`, {});
      setAlerts(prev => prev.map(a => a.id === alertId ? { ...a, acknowledged: true } : a));
    } catch { /* silent */ }
  }, []);

  if (!open) return null;

  const unacknowledgedCount = alerts.filter(a => !a.acknowledged).length;

  return (
    <div style={{
      position: 'fixed', top: 'var(--topbar-h)', right: 16,
      width: 380, maxHeight: 'calc(100vh - 80px)',
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-default)',
      borderRadius: 'var(--r-lg)',
      boxShadow: 'var(--shadow-modal)',
      zIndex: 1000,
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
      animation: 'fade-in var(--dur-fast) var(--ease-apple)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: 'var(--s4) var(--s5)',
        borderBottom: '1px solid var(--separator)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s2)' }}>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 14, fontWeight: 600, color: 'var(--label-primary)' }}>
            告警通知
          </span>
          {unacknowledgedCount > 0 && (
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 10,
              color: 'var(--red)', background: 'var(--red-soft)',
              padding: '1px 6px', borderRadius: 'var(--r-pill)',
            }}>
              {unacknowledgedCount}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', color: 'var(--label-tertiary)',
            fontSize: 18, cursor: 'pointer', padding: '0 4px',
          }}
        >
          ✕
        </button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 'var(--s3)' }}>
        {loading && alerts.length === 0 && (
          <div style={{ padding: 'var(--s8)', textAlign: 'center', color: 'var(--label-tertiary)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            加载中...
          </div>
        )}

        {!loading && alerts.length === 0 && (
          <div style={{ padding: 'var(--s8)', textAlign: 'center', color: 'var(--label-quaternary)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            暂无告警
          </div>
        )}

        {alerts.map(alert => {
          const fallback = { bg: 'var(--accent-soft)', border: 'var(--accent)', icon: '🔵' };
          const sev = SEVERITY_COLORS[alert.severity] ?? fallback;
          return (
            <div
              key={alert.id}
              style={{
                display: 'flex', gap: 'var(--s3)', padding: 'var(--s3) var(--s4)',
                marginBottom: 'var(--s2)',
                background: alert.acknowledged ? 'transparent' : sev.bg,
                border: `1px solid ${alert.acknowledged ? 'var(--border-subtle)' : sev.border}`,
                borderRadius: 'var(--r-md)',
                opacity: alert.acknowledged ? 0.5 : 1,
              }}
            >
              <span style={{ fontSize: 14, lineHeight: '20px' }}>{sev.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600, color: 'var(--label-primary)', marginBottom: 2 }}>
                  {alert.title}
                  {alert.symbol && (
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', marginLeft: 6 }}>
                      {alert.symbol}
                    </span>
                  )}
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--label-secondary)', lineHeight: 1.4 }}>
                  {alert.message}
                </div>
              </div>
              {!alert.acknowledged && (
                <button
                  onClick={() => acknowledgeAlert(alert.id)}
                  style={{
                    background: 'none', border: '1px solid var(--border-default)',
                    borderRadius: 'var(--r-xs)', padding: '2px 8px',
                    fontFamily: 'var(--font-mono)', fontSize: 10,
                    color: 'var(--label-tertiary)', cursor: 'pointer',
                    alignSelf: 'center', whiteSpace: 'nowrap',
                  }}
                >
                  确认
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div style={{
        padding: 'var(--s3) var(--s4)',
        borderTop: '1px solid var(--separator)',
        display: 'flex', justifyContent: 'center',
      }}>
        <button
          onClick={fetchAlerts}
          style={{
            background: 'none', border: '1px solid var(--border-default)',
            borderRadius: 'var(--r-sm)', padding: '6px 16px',
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--label-secondary)', cursor: 'pointer',
          }}
        >
          刷新
        </button>
      </div>
    </div>
  );
});
