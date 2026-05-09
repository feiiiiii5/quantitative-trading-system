import { createContext, useCallback, useContext, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { cn } from '@/shared/lib/cn';

type ToastType = 'info' | 'success' | 'warning' | 'error' | 'critical';

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  autoDismiss?: boolean;
}

interface ToastContextValue {
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue>({
  addToast: () => {},
  removeToast: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}

const MAX_VISIBLE = 5;
const AUTO_DISMISS_MS = 4000;

const TYPE_STYLES: Record<ToastType, string> = {
  info: 'border-l-[var(--text-accent)] bg-[var(--text-accent)]/5',
  success: 'border-l-[var(--color-bid)] bg-[var(--color-bid)]/5',
  warning: 'border-l-[var(--color-warning)] bg-[var(--color-warning)]/5',
  error: 'border-l-[var(--color-ask)] bg-[var(--color-ask)]/5',
  critical: 'border-l-[var(--color-critical)] bg-[var(--color-critical)]/5',
};

const TYPE_ICONS: Record<ToastType, string> = {
  info: 'ℹ',
  success: '✓',
  warning: '⚠',
  error: '✕',
  critical: '⛔',
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const newToast: Toast = {
      ...toast,
      id,
      autoDismiss: toast.autoDismiss ?? (toast.type !== 'error' && toast.type !== 'critical'),
    };
    setToasts((prev) => [...prev.slice(-(MAX_VISIBLE - 1)), newToast]);

    if (newToast.autoDismiss) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, AUTO_DISMISS_MS);
    }
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ addToast, removeToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              initial={{ opacity: 0, x: 100, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 100, scale: 0.95 }}
              transition={{ duration: 0.2 }}
              className={cn(
                'pointer-events-auto min-w-[280px] max-w-[380px] border-l-4 rounded-[var(--radius-md)] p-[var(--space-3)] bg-[var(--bg-elevated)] shadow-lg',
                TYPE_STYLES[toast.type]
              )}
            >
              <div className="flex items-start gap-2">
                <span className="text-[var(--font-size-sm)]">{TYPE_ICONS[toast.type]}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-[var(--font-size-sm)] font-medium text-[var(--text-primary)]">
                    {toast.title}
                  </div>
                  {toast.message && (
                    <div className="text-[var(--font-size-xs)] text-[var(--text-secondary)] mt-0.5">
                      {toast.message}
                    </div>
                  )}
                </div>
                {!toast.autoDismiss && (
                  <button
                    onClick={() => removeToast(toast.id)}
                    className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-[var(--font-size-xs)]"
                  >
                    ✕
                  </button>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
