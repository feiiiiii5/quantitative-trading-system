export interface DepthLevel {
  price: number;
  size: number;
  total: number;
}

export class OrderBookRenderer {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Failed to get 2D context');
    this.ctx = ctx;
    this.resize(canvas.clientWidth, canvas.clientHeight);
  }

  render(bids: DepthLevel[], asks: DepthLevel[], maxTotal: number): void {
    const w = this.canvas.width;
    const h = this.canvas.height;
    const dpr = window.devicePixelRatio || 1;
    const bidCount = Math.min(bids.length, 20);
    const askCount = Math.min(asks.length, 20);
    const totalRows = bidCount + askCount || 1;
    const rowHeight = h / totalRows;

    this.ctx.clearRect(0, 0, w, h);

    this.ctx.fillStyle = 'rgba(255, 77, 106, 0.25)';
    for (let i = 0; i < askCount; i++) {
      const level = asks[i];
      const barWidth = maxTotal > 0 ? (level.total / maxTotal) * w : 0;
      this.ctx.fillRect(0, i * rowHeight, barWidth, rowHeight - dpr);
    }

    this.ctx.fillStyle = 'rgba(0, 200, 150, 0.25)';
    for (let i = 0; i < bidCount; i++) {
      const level = bids[i];
      const barWidth = maxTotal > 0 ? (level.total / maxTotal) * w : 0;
      const y = (askCount + i) * rowHeight;
      this.ctx.fillRect(w - barWidth, y, barWidth, rowHeight - dpr);
    }
  }

  resize(width: number, height: number): void {
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = width * dpr;
    this.canvas.height = height * dpr;
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.ctx.scale(dpr, dpr);
  }

  destroy(): void {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }
}
