export function formatNumber(n: number, decimals = 2): string {
  if (Number.isNaN(n) || !Number.isFinite(n)) return '—';
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function formatPercent(n: number, decimals = 2): string {
  if (Number.isNaN(n) || !Number.isFinite(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(decimals)}%`;
}

export function formatRatio(n: number, decimals = 2): string {
  if (Number.isNaN(n) || !Number.isFinite(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${(n * 100).toFixed(decimals)}%`;
}

export function formatPrice(n: number): string {
  return formatNumber(n, 2);
}

export function formatVolume(n: number): string {
  if (Number.isNaN(n) || !Number.isFinite(n)) return '—';
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`;
  return n.toLocaleString();
}

export function formatAmount(n: number): string {
  if (Number.isNaN(n) || !Number.isFinite(n)) return '—';
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}万亿`;
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`;
  return n.toLocaleString();
}

export function priceColor(change: number): string {
  if (change > 0) return 'var(--signal-rise)';
  if (change < 0) return 'var(--signal-fall)';
  return 'var(--label-secondary)';
}

export function priceClass(change: number): string {
  if (change > 0) return 'price-rise';
  if (change < 0) return 'price-fall';
  return 'price-flat';
}
