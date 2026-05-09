const priceFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const priceFormatterCrypto = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 8,
});

const pctFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: 'always',
});

const volumeFormatter = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 2,
});

const amountFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  style: 'currency',
  currency: 'USD',
});

export function formatPrice(value: number, isCrypto = false): string {
  return isCrypto ? priceFormatterCrypto.format(value) : priceFormatter.format(value);
}

export function formatPct(value: number): string {
  return pctFormatter.format(value) + '%';
}

export function formatVolume(value: number): string {
  return volumeFormatter.format(value);
}

export function formatAmount(value: number): string {
  return amountFormatter.format(value);
}

export function formatTime(ts: number | Date, tz = 'Asia/Shanghai'): string {
  const d = ts instanceof Date ? ts : new Date(ts);
  return d.toLocaleTimeString('en-US', { timeZone: tz, hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function formatDate(ts: number | Date, tz = 'Asia/Shanghai'): string {
  const d = ts instanceof Date ? ts : new Date(ts);
  return d.toLocaleDateString('en-US', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' });
}
