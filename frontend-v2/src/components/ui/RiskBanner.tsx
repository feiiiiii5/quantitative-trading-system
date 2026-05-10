import { memo } from 'react';
import type { RiskLevel } from '@/types';
import { KillSwitch } from '@/components/ui/KillSwitch';

const LEVEL_CONFIG: Record<RiskLevel, { bg: string; color: string; label: string }> = {
  LOW: { bg: 'rgba(78,158,110,0.06)', color: '#4E9E6E', label: 'LOW' },
  MEDIUM: { bg: 'rgba(212,160,74,0.06)', color: '#D4A04A', label: 'MEDIUM' },
  HIGH: { bg: 'rgba(212,88,74,0.08)', color: '#D4584A', label: 'HIGH' },
  CRITICAL: { bg: 'rgba(212,88,74,0.12)', color: '#D4584A', label: 'CRITICAL' },
};

interface RiskBannerProps {
  level: RiskLevel;
  maxDrawdown: number;
  alertCount: number;
}

export const RiskBanner = memo(function RiskBanner({ level, maxDrawdown, alertCount }: RiskBannerProps) {
  const config = LEVEL_CONFIG[level];
  const isCritical = level === 'CRITICAL' || level === 'HIGH';

  return (
    <div style={{
      height: isCritical ? '40px' : '32px',
      display: 'flex', alignItems: 'center', gap: '16px',
      padding: '0 20px',
      background: config.bg,
      borderBottom: `1px solid ${config.color}22`,
      transition: 'height 280ms ease-out, background 280ms ease-out',
      overflow: 'hidden',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span style={{
          width: '6px', height: '6px', borderRadius: '50%',
          background: config.color,
          animation: isCritical ? 'pulse-dot 1s ease-in-out infinite' : 'none',
        }} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: config.color, fontWeight: 600, letterSpacing: '0.08em' }}>
          RISK: {config.label}
        </span>
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-tertiary)' }}>
        MAX DD: <span style={{ color: '#D4584A' }}>{(maxDrawdown * 100).toFixed(2)}%</span>
      </span>
      {alertCount > 0 && (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-tertiary)' }}>
          ALERTS: <span style={{ color: config.color }}>{alertCount}</span>
        </span>
      )}
      <div style={{ flex: 1 }} />
      <KillSwitch />
    </div>
  );
});
