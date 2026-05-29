import { useEffect, useRef, useCallback } from 'react';

type HotkeyHandler = () => void;

export function useHotkeys(map: Record<string, HotkeyHandler>): void {
  const mapRef = useRef(map);
  mapRef.current = map;

  const handler = useCallback((e: KeyboardEvent) => {
    const target = e.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
      if (e.key !== 'Escape') return;
      (target as HTMLElement).blur();  // 在 input 中按 Escape 先失焦再执行 handler
    }

    const parts: string[] = [];
    if (e.metaKey || e.ctrlKey) parts.push('cmd');
    if (e.shiftKey) parts.push('shift');
    if (e.altKey) parts.push('alt');
    parts.push(e.key.toLowerCase());
    const combo = parts.join('+');

    const fn = mapRef.current[combo];
    if (fn) {
      e.preventDefault();
      fn();
    }
  }, []);

  useEffect(() => {
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handler]);
}
