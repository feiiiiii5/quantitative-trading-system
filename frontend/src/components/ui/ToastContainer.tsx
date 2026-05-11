import { useEffect, memo } from 'react';
import { useToastStore, type Toast } from '@/stores/toast';

const TYPE_STYLES: Record<Toast['type'], { bg: string; border: string; icon: string }> = {
  info: { bg: 'rgba(10,132,255,0.08)', border: 'rgba(10,132,255,0.20)', icon: 'ℹ' },
  success: { bg: 'rgba(0,200,83,0.08)', border: 'rgba(0,200,83,0.20)', icon: '✓' },
  warn: { bg: 'rgba(255,145,0,0.08)', border: 'rgba(255,145,0,0.20)', icon: '⚠' },
  error: { bg: 'rgba(255,23,68,0.08)', border: 'rgba(255,23,68,0.20)', icon: '✕' },
};

const ToastItem = memo(function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const style = TYPE_STYLES[toast.type];

  useEffect(() => {
    if (toast.type === 'error') return;
    const id = setTimeout(onDismiss, toast.duration);
    return () => clearTimeout(id);
  }, [toast, onDismiss]);

  return (
    <div
      onClick={onDismiss}
      style={{
        background: style.bg,
        border: `1px solid ${style.border}`,
        borderRadius: 'var(--r-md)',
        padding: '12px 16px',
        cursor: toast.type === 'error' ? 'pointer' : 'default',
        animation: 'slide-in-right 300ms var(--ease-apple)',
        display: 'flex',
        gap: 10,
        alignItems: 'flex-start',
        minWidth: 280,
        maxWidth: 380,
      }}
    >
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: style.border.replace('0.20', '0.80') }}>
        {style.icon}
      </span>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--label-primary)', fontWeight: 500 }}>
          {toast.title}
        </div>
        {toast.body && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)', marginTop: 4 }}>
            {toast.body}
          </div>
        )}
      </div>
    </div>
  );
});

export const ToastContainer = memo(function ToastContainer() {
  const { toasts, removeToast } = useToastStore();

  if (toasts.length === 0) return null;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 20,
        right: 20,
        zIndex: 9000,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => (
        <div key={t.id} style={{ pointerEvents: 'auto' }}>
          <ToastItem toast={t} onDismiss={() => removeToast(t.id)} />
        </div>
      ))}
    </div>
  );
});
