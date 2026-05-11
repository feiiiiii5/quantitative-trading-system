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

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  addToast: (toast) => {
    const id = String(++nextId);
    const createdAt = Date.now();
    set((s) => ({ toasts: [...s.toasts, { ...toast, id, createdAt }] }));
  },
  removeToast: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));
