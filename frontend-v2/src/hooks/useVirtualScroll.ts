import { useState, useRef, useCallback } from 'react';

interface VirtualScrollOptions {
  itemCount: number;
  itemHeight: number;
  overscan?: number;
}

export function useVirtualScroll({ itemCount, itemHeight, overscan = 5 }: VirtualScrollOptions) {
  const [scrollTop, setScrollTop] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const totalHeight = itemCount * itemHeight;

  const startIdx = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
  const endIdx = Math.min(itemCount, Math.ceil((scrollTop + (containerRef.current?.clientHeight ?? 600)) / itemHeight) + overscan);

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
