import type { OrderBookLevel, GroupSize } from '../model/types';

export function groupLevels(levels: OrderBookLevel[], groupSize: GroupSize): OrderBookLevel[] {
  if (groupSize === 0.01) return levels;

  const grouped = new Map<number, { size: number; total: number }>();

  for (const level of levels) {
    const groupedPrice = Math.floor(level.price / groupSize) * groupSize;
    const existing = grouped.get(groupedPrice);
    if (existing) {
      existing.size += level.size;
      existing.total = Math.max(existing.total, level.total);
    } else {
      grouped.set(groupedPrice, { size: level.size, total: level.total });
    }
  }

  return Array.from(grouped.entries())
    .map(([price, { size, total }]) => ({
      price,
      size,
      total,
      depth: total,
    }))
    .sort((a, b) => b.price - a.price);
}
