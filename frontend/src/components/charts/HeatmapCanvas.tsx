import { memo, useCallback } from 'react';
import { useCanvas } from '@/hooks/useCanvas';
import type { SectorData } from '@/types';

interface HeatmapCanvasProps {
  sectors: SectorData[];
  width?: number;
  height?: number;
}

interface TreemapItem {
  name: string;
  value: number;
  change_pct: number;
}

interface TreemapRect {
  x: number;
  y: number;
  w: number;
  h: number;
  item: TreemapItem;
}

function worstAspectRatio(row: number[], sideLength: number): number {
  if (row.length === 0 || sideLength <= 0) return Infinity;
  const total = row.reduce((a, b) => a + b, 0);
  if (total <= 0) return Infinity;
  const s2 = sideLength * sideLength;
  const t2 = total * total;
  let worst = 0;
  for (const r of row) {
    if (r <= 0) continue;
    const ratio = Math.max((s2 * r) / t2, t2 / (s2 * r));
    if (ratio > worst) worst = ratio;
  }
  return worst;
}

function layoutRow(
  row: TreemapItem[],
  rowAreas: number[],
  rect: { x: number; y: number; w: number; h: number },
): { rects: TreemapRect[]; remaining: { x: number; y: number; w: number; h: number } } {
  const totalArea = rowAreas.reduce((a, b) => a + b, 0);
  const isWider = rect.w >= rect.h;
  const sideLength = isWider ? rect.h : rect.w;
  const stripSize = totalArea / sideLength;

  const rects: TreemapRect[] = [];
  let offset = 0;

  for (let i = 0; i < row.length; i++) {
    const itemLength = rowAreas[i]! / stripSize;
    if (isWider) {
      rects.push({ x: rect.x, y: rect.y + offset, w: stripSize, h: itemLength, item: row[i]! });
    } else {
      rects.push({ x: rect.x + offset, y: rect.y, w: itemLength, h: stripSize, item: row[i]! });
    }
    offset += itemLength;
  }

  const remaining = isWider
    ? { x: rect.x + stripSize, y: rect.y, w: rect.w - stripSize, h: rect.h }
    : { x: rect.x, y: rect.y + stripSize, w: rect.w, h: rect.h - stripSize };

  return { rects, remaining };
}

function squarify(
  items: TreemapItem[],
  rect: { x: number; y: number; w: number; h: number },
): TreemapRect[] {
  if (items.length === 0 || rect.w <= 0 || rect.h <= 0) return [];

  const sorted = [...items].sort((a, b) => b.value - a.value);
  const totalValue = sorted.reduce((sum, it) => sum + it.value, 0);
  if (totalValue <= 0) return [];

  const totalArea = rect.w * rect.h;
  const normalized = sorted.map(it => ({
    item: it,
    area: (it.value / totalValue) * totalArea,
  }));

  const result: TreemapRect[] = [];
  let remaining = { ...rect };
  let row: TreemapItem[] = [];
  let rowAreas: number[] = [];

  for (const { item, area } of normalized) {
    const sideLength = Math.min(remaining.w, remaining.h);
    const newRow = [...row, item];
    const newRowAreas = [...rowAreas, area];

    if (
      row.length === 0 ||
      worstAspectRatio(newRowAreas, sideLength) <= worstAspectRatio(rowAreas, sideLength)
    ) {
      row = newRow;
      rowAreas = newRowAreas;
    } else {
      const { rects, remaining: newRemaining } = layoutRow(row, rowAreas, remaining);
      result.push(...rects);
      remaining = newRemaining;
      row = [item];
      rowAreas = [area];
    }
  }

  if (row.length > 0 && remaining.w > 0 && remaining.h > 0) {
    const { rects } = layoutRow(row, rowAreas, remaining);
    result.push(...rects);
  }

  return result;
}

function getColor(changePct: number, maxAbs: number): string {
  const absPct = Math.abs(changePct);
  if (absPct < 0.01) return 'rgba(255,255,255,0.06)';

  const norm = Math.min(absPct / maxAbs, 1);
  if (changePct > 0) {
    const r = Math.round(40 + norm * 215);
    const g = Math.round(norm * 23);
    const b = Math.round(norm * 68);
    return `rgb(${r},${g},${b})`;
  }
  const g = Math.round(40 + norm * 160);
  const b = Math.round(20 + norm * 63);
  return `rgb(0,${g},${b})`;
}

function truncateText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let truncated = text;
  while (truncated.length > 1 && ctx.measureText(truncated + '…').width > maxWidth) {
    truncated = truncated.slice(0, -1);
  }
  return truncated + '…';
}

export const HeatmapCanvas = memo(function HeatmapCanvas({
  sectors,
}: HeatmapCanvasProps) {
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (sectors.length === 0) return;
      ctx.clearRect(0, 0, w, h);

      const items: TreemapItem[] = sectors.map(s => ({
        name: s.name,
        value: Math.max(s.amount, 0.01),
        change_pct: s.change_pct,
      }));

      const gap = 2;
      const rects = squarify(items, { x: 0, y: 0, w, h });
      const maxAbs = Math.max(...sectors.map(s => Math.abs(s.change_pct ?? 0)), 0.01);

      for (const rect of rects) {
        const rx = rect.x + gap / 2;
        const ry = rect.y + gap / 2;
        const rw = rect.w - gap;
        const rh = rect.h - gap;
        if (rw <= 0 || rh <= 0) continue;

        ctx.fillStyle = getColor(rect.item.change_pct, maxAbs);
        ctx.beginPath();
        ctx.roundRect(rx, ry, rw, rh, 3);
        ctx.fill();

        if (rw > 50 && rh > 30) {
          const maxTextWidth = rw - 8;
          const centerY = ry + rh / 2;

          ctx.fillStyle = 'rgba(255,255,255,0.9)';
          ctx.font = 'bold 11px system-ui';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';

          const name = truncateText(ctx, rect.item.name, maxTextWidth);
          ctx.fillText(name, rx + rw / 2, centerY - 7);

          ctx.fillStyle = 'rgba(255,255,255,0.65)';
          ctx.font = '10px JetBrains Mono, monospace';
          const pct =
            rect.item.change_pct >= 0
              ? `+${rect.item.change_pct.toFixed(2)}%`
              : `${rect.item.change_pct.toFixed(2)}%`;
          ctx.fillText(pct, rx + rw / 2, centerY + 7);
        }
      }
    },
    [sectors],
  );

  const { ref } = useCanvas(draw, [sectors]);

  return <canvas ref={ref} style={{ width: '100%', height: '100%' }} />;
});
