import { useState, useRef, useCallback, useEffect } from 'react';

interface VirtualScrollOptions {
  itemCount: number;
  itemHeight: number;
  overscan?: number;
}

export function useVirtualScroll({ itemCount, itemHeight, overscan = 5 }: VirtualScrollOptions) {
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setContainerHeight(el.clientHeight);
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerHeight(entry.contentRect.height);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const totalHeight = itemCount * itemHeight;

  const startIdx = containerHeight === 0
    ? 0
    : Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
  const endIdx = containerHeight === 0
    ? Math.min(itemCount, 20)
    : Math.min(itemCount, Math.ceil((scrollTop + containerHeight) / itemHeight) + overscan);

  const visibleItems = Array.from({ length: endIdx - startIdx }, (_, i) => startIdx + i);

  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  const getItemStyle = useCallback((index: number): React.CSSProperties => ({
    position: 'absolute',
    top: index * itemHeight,
    left: 0,
    width: '100%',
    height: itemHeight,
  }), [itemHeight]);

  return {
    containerRef,
    totalHeight,
    visibleItems,
    onScroll,
    getItemStyle,
    startIdx,
    endIdx,
  };
}
