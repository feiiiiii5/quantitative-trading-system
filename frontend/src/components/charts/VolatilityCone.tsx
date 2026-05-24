import { memo, useCallback } from 'react';
import { useCanvas } from '@/hooks/useCanvas';
import { safeMin, safeMax } from '@/utils/format';

interface VolatilityConeProps {
  dates: string[];
  historical: number[];
  implied: number[];
  width?: number;
  height?: number;
}

export const VolatilityCone = memo(function VolatilityCone({ dates, historical, implied, width = 400, height = 200 }: VolatilityConeProps) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    if (historical.length < 2) return;
    ctx.clearRect(0, 0, w, h);
    const pad = { top: 16, right: 16, bottom: 24, left: 40 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;
    const allVals = [...historical, ...implied].filter(v => isFinite(v));
    if (allVals.length === 0) return;
    const minV = safeMin(allVals) * 0.9;
    const maxV = safeMax(allVals) * 1.1;
    const range = maxV - minV || 1;

    ctx.strokeStyle = 'rgba(255,255,255,0.03)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (i / 4) * ch;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
    }

    const drawLine = (data: number[], color: string) => {
      ctx.beginPath();
      for (let i = 0; i < data.length; i++) {
        const x = pad.left + (i / (data.length - 1)) * cw;
        const y = pad.top + (1 - (data[i]! - minV) / range) * ch;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    };

    drawLine(historical, '#0A84FF');
    if (implied.length > 0) drawLine(implied, '#FF9100');

    ctx.fillStyle = 'rgba(255,255,255,0.30)';
    ctx.font = "9px 'SF Mono','Fira Code','JetBrains Mono',monospace";
    ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(dates.length / 5));
    for (let i = 0; i < dates.length; i += step) {
      const x = pad.left + (i / (dates.length - 1)) * cw;
      ctx.fillText(dates[i]!.slice(0, 7), x, h - 4);
    }
  }, [dates, historical, implied]);

  const { ref } = useCanvas(draw, [dates, historical, implied]);

  return <canvas ref={ref} style={{ width, height }} />;
});
