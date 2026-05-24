import { memo, useCallback } from 'react';
import { useCanvas } from '@/hooks/useCanvas';
import { colors } from '@/design/tokens/colors';
import { formatAmount, safeMin, safeMax } from '@/utils/format';

interface WaterfallItem {
  label: string;
  value: number;
  isTotal?: boolean;
}

interface WaterfallChartProps {
  items: WaterfallItem[];
  height?: number;
}

export const WaterfallChart = memo(function WaterfallChart({ items, height = 260 }: WaterfallChartProps) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    if (items.length === 0) return;
    ctx.clearRect(0, 0, w, h);

    const pad = { t: 24, r: 20, b: 40, l: 60 };
    const chartW = w - pad.l - pad.r;
    const chartH = h - pad.t - pad.b;

    let running = 0;
    const bars = items.map(item => {
      const base = item.isTotal ? 0 : running;
      const top = item.isTotal ? running : running + item.value;
      if (!item.isTotal) running += item.value;
      return { ...item, base, top };
    });

    const allVals = bars.flatMap(b => [b.base, b.top]);
    const minV = safeMin([...allVals, 0]);
    const maxV = safeMax([...allVals, 0]);
    const range = Math.max(maxV - minV, 1);

    const gap = chartW / items.length;
    const barW = gap * 0.6;
    const toY = (v: number) => pad.t + chartH - ((v - minV) / range) * chartH;

    const zeroY = toY(0);
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.l, zeroY);
    ctx.lineTo(w - pad.r, zeroY);
    ctx.stroke();

    for (let i = 0; i < bars.length; i++) {
      const bar = bars[i]!;
      const x = pad.l + i * gap + (gap - barW) / 2;
      const y1 = toY(Math.max(bar.base, bar.top));
      const y2 = toY(Math.min(bar.base, bar.top));
      const barH = Math.max(y2 - y1, 2);
      const isPos = bar.value >= 0;

      ctx.fillStyle = bar.isTotal
        ? (bar.top >= 0 ? colors.market.rise : colors.market.fall)
        : isPos ? 'rgba(255,59,92,0.8)' : 'rgba(0,217,160,0.8)';
      ctx.beginPath();
      ctx.roundRect(x, y1, barW, barH, [3, 3, 0, 0]);
      ctx.fill();

      if (i < bars.length - 1 && !bar.isTotal) {
        ctx.strokeStyle = 'rgba(255,255,255,0.15)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x + barW, toY(bar.top));
        ctx.lineTo(x + barW + (gap - barW), toY(bar.top));
        ctx.stroke();
        ctx.setLineDash([]);
      }

      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.font = '9px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(bar.label, x + barW / 2, h - pad.b + 14);

      const labelY = isPos ? y1 - 4 : y2 + 12;
      ctx.fillStyle = isPos ? colors.market.rise : colors.market.fall;
      ctx.font = 'bold 10px monospace';
      ctx.fillText(formatAmount(bar.value), x + barW / 2, labelY);
    }
  }, [items]);

  const { ref } = useCanvas(draw, [items]);
  return <canvas ref={ref} style={{ width: '100%', height }} />;
});
