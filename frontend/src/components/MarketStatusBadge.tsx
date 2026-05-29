import { memo, useState, useEffect } from 'react';

type MarketStatus = 'pre' | 'open' | 'after' | 'closed';

function getMarketStatus(): MarketStatus {
  const now = new Date();
  const h = now.getHours();
  const m = now.getMinutes();
  const t = h * 60 + m;
  const day = now.getDay();
  if (day === 0 || day === 6) return 'closed';
  if (t >= 570 && t < 585) return 'pre';
  if (t >= 585 && t < 690) return 'open';
  if (t >= 780 && t < 900) return 'open';
  if (t >= 690 && t < 780) return 'closed';  // 午休 11:30-13:00 应为 closed 非 after
  return 'closed';
}

const STATUS_CONFIG: Record<MarketStatus, { label: string; color: string; pulse: boolean }> = {
  open:   { label: 'OPEN',   color: '#00C853', pulse: true },
  pre:    { label: 'PRE',    color: '#FF9100', pulse: false },
  after:  { label: 'AFTER',  color: '#0A84FF', pulse: false },
  closed: { label: 'CLOSED', color: 'rgba(255,255,255,0.2)', pulse: false },
};

export const MarketStatusBadge = memo(function MarketStatusBadge() {
  const [status, setStatus] = useState<MarketStatus>(getMarketStatus);

  useEffect(() => {
    const id = setInterval(() => setStatus(getMarketStatus()), 30_000);
    return () => clearInterval(id);
  }, []);

  const config = STATUS_CONFIG[status];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: config.color,
        boxShadow: config.pulse ? `0 0 6px ${config.color}` : 'none',
        animation: config.pulse ? 'pulse 2s infinite' : 'none',
      }} />
      <span style={{
        fontSize: 10, fontFamily: 'var(--font-mono)',
        color: config.color, letterSpacing: '0.1em',
        fontVariantNumeric: 'tabular-nums',
      }}>
        {config.label}
      </span>
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
    </div>
  );
});
