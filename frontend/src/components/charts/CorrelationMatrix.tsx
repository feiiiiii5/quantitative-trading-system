import { memo, useCallback } from 'react';
import { useCanvas } from '@/hooks/useCanvas';

interface CorrelationMatrixProps {
  labels: string[];
  values: number[][];
  width?: number;
  height?: number;
}

export const CorrelationMatrix = memo(function CorrelationMatrix({ labels, values, width = 400, height = 400 }: CorrelationMatrixProps) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    if (labels.length === 0 || values.length === 0) return;
    ctx.clearRect(0, 0, w, h);
    const n = labels.length;
    const labelSpace = 60;
    const cellW = (w - labelSpace) / n;
    const cellH = (h - labelSpace) / n;
    const offsetX = labelSpace;
    const offsetY = 0;

    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const v = values[i]?.[j] ?? 0;
        const x = offsetX + j * cellW;
        const y = offsetY + i * cellH;
        let r: number, g: number, b: number;
        if (v >= 0) {
          r = Math.round(255 * Math.abs(v));
          g = Math.round(23 * (1 - Math.abs(v) * 0.6));
          b = Math.round(68 * (1 - Math.abs(v) * 0.6));
        } else {
          r = Math.round(10 * (1 - Math.abs(v) * 0.3));
          g = Math.round(132 * (0.5 + Math.abs(v) * 0.5));
          b = Math.round(255 * (0.5 + Math.abs(v) * 0.5));
        }
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillRect(x, y, cellW - 1, cellH - 1);

        if (Math.abs(v) > 0.3) {
          ctx.fillStyle = 'rgba(255,255,255,0.7)';
          ctx.font = '9px JetBrains Mono';
          ctx.textAlign = 'center';
          ctx.fillText(v.toFixed(2), x + cellW / 2, y + cellH / 2 + 3);
        }
      }
    }

    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '9px JetBrains Mono';
    ctx.textAlign = 'right';
    for (let i = 0; i < n; i++) {
      ctx.fillText(labels[i]!, offsetX - 4, offsetY + i * cellH + cellH / 2 + 3);
    }
    ctx.textAlign = 'center';
    for (let j = 0; j < n; j++) {
      ctx.save();
      ctx.translate(offsetX + j * cellW + cellW / 2, h - 4);
      ctx.fillText(labels[j]!, 0, 0);
      ctx.restore();
    }
  }, [labels, values]);

  const { ref } = useCanvas(draw, [labels, values]);

  return <canvas ref={ref} style={{ width, height }} />;
});
