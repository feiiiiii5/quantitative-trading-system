import { memo, useCallback } from 'react';
import { useCanvas } from '@/hooks/useCanvas';
import type { SectorData } from '@/types';

interface HeatmapCanvasProps {
  sectors: SectorData[];
  width?: number;
  height?: number;
}

export const HeatmapCanvas = memo(function HeatmapCanvas({ sectors, width = 400, height = 200 }: HeatmapCanvasProps) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    if (sectors.length === 0) return;
    ctx.clearRect(0, 0, w, h);
    const maxAbs = Math.max(...sectors.map(s => Math.abs(s.change_pct ?? 0)), 0.01);
    const cols = 6;
    const rows = Math.ceil(sectors.length / cols);
    const cellW = w / cols;
    const cellH = h / rows;
    const gap = 2;

    for (let i = 0; i < sectors.length; i++) {
      const sec = sectors[i]!;
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x = col * cellW + gap;
      const y = row * cellH + gap;
      const cw = cellW - gap * 2;
      const ch = cellH - gap * 2;

      const norm = Math.min(Math.abs(sec.change_pct ?? 0) / maxAbs, 1);
      let r: number, g: number, b: number;
      if (sec.change_pct >= 0) {
        r = Math.round(212 * (0.15 + norm * 0.85));
        g = Math.round(88 * (1 - norm * 0.5));
        b = Math.round(74 * (1 - norm * 0.5));
      } else {
        r = Math.round(78 * (1 - norm * 0.3));
        g = Math.round(158 * (0.3 + norm * 0.7));
        b = Math.round(110 * (0.3 + norm * 0.7));
      }

      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.beginPath();
      ctx.roundRect(x, y, cw, ch, 3);
      ctx.fill();

      ctx.fillStyle = 'rgba(255,255,255,0.85)';
      ctx.font = '10px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText(sec.name, x + cw / 2, y + ch / 2 - 3, cw - 4);

      ctx.fillStyle = 'rgba(255,255,255,0.6)';
      ctx.font = '9px JetBrains Mono, monospace';
      const pct = sec.change_pct >= 0 ? `+${sec.change_pct.toFixed(2)}%` : `${sec.change_pct.toFixed(2)}%`;
      ctx.fillText(pct, x + cw / 2, y + ch / 2 + 9, cw - 4);
    }
  }, [sectors]);

  const { ref } = useCanvas(draw, [sectors]);

  return <canvas ref={ref} style={{ width, height }} />;
});
