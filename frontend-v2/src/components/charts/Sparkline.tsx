import { memo } from 'react';
import { useCanvas } from '@/hooks/useCanvas';

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
}

export const Sparkline = memo(function Sparkline({ data, width = 50, height = 14, color }: SparklineProps) {
  const drawColor = color ?? 'var(--signal-rise, #D4584A)';

  const { ref } = useCanvas((ctx, w, h) => {
    if (data.length < 2) return;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    ctx.clearRect(0, 0, w, h);
    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const x = (i / (data.length - 1)) * w;
      const y = h - 1 - ((data[i]! - min) / range) * (h - 2);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = drawColor;
    ctx.lineWidth = 1.2;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
  }, [data, drawColor]);

  return <canvas ref={ref} style={{ width, height }} />;
});
