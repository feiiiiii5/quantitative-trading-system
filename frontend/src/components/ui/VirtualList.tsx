import { memo, type ReactNode, type CSSProperties } from 'react';
import { useVirtualScroll } from '@/hooks/useVirtualScroll';

interface VirtualListProps<T> {
  items: T[];
  itemHeight: number;
  renderItem: (item: T, index: number, style: CSSProperties) => ReactNode;
  overscan?: number;
}

export const VirtualList = memo(function VirtualList<T>({
  items,
  itemHeight,
  renderItem,
  overscan = 5,
}: VirtualListProps<T>) {
  const { containerRef, totalHeight, visibleItems, onScroll, getItemStyle } = useVirtualScroll({
    itemCount: items.length,
    itemHeight,
    overscan,
  });

  return (
    <div
      ref={containerRef}
      onScroll={onScroll}
      style={{ flex: 1, overflow: 'auto', position: 'relative' }}
    >
      <div style={{ height: totalHeight, position: 'relative' }}>
        {visibleItems.map((idx) => renderItem(items[idx]!, idx, getItemStyle(idx)))}
      </div>
    </div>
  );
}) as <T>(
  props: VirtualListProps<T>,
) => ReactNode;
