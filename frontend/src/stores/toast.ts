import { create } from 'zustand';

export interface Toast {
  id: string;
  type: 'info' | 'success' | 'warn' | 'error';
  title: string;
  body?: string;
  duration: number;
  createdAt: number;
}

interface ToastState {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, 'id' | 'createdAt'>) => void;
  removeToast: (id: string) => void;
}

let nextId = 0;

const MAX_TOASTS = 5;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  addToast: (toast) => {
    const id = String(++nextId);
    const createdAt = Date.now();
    set((s) => {
      const duplicate = s.toasts.some(
        (t) => t.title === toast.title && t.type === toast.type,
      );
      if (duplicate) return s;
      const next = [...s.toasts, { ...toast, id, createdAt }];
      return { toasts: next.length > MAX_TOASTS ? next.slice(-MAX_TOASTS) : next };
    });
  },
  removeToast: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));
