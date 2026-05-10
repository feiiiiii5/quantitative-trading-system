import { memo, type CSSProperties } from 'react';
import type { RiskLevel } from '@/types';
import { Badge } from '@/components/ui/Badge';
import { KillSwitch } from '@/components/ui/KillSwitch';

const LEVEL_BADGE_VARIANT: Record<RiskLevel, 'buy' | 'warn' | 'sell' | 'sell'> = {
  LOW: 'buy',
  MEDIUM: 'warn',
  HIGH: 'sell',
  CRITICAL: 'sell',
};

const LEVEL_BG: Record<RiskLevel, string> = {
  LOW: 'transparent',
  MEDIUM: 'var(--orange-soft)',
  HIGH: 'var(--red-soft)',
  CRITICAL: 'var(--red-soft)',
};

interface RiskBannerProps {
  level: RiskLevel;
  maxDrawdown: number;
  alertCount: number;
}

export const RiskBanner = memo(function RiskBanner({ level, maxDrawdown, alertCount }: RiskBannerProps) {
  const visible = level !== 'LOW';
  const bannerHeight: CSSProperties = {
    height: visible ? '44px' : '0px',
    overflow: 'hidden',
    transition: 'height var(--dur-base) var(--ease-apple), background var(--dur-base) var(--ease-apple)',
  };

  return (
    <div
      style={{
        ...bannerHeight,
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--s4)',
        padding: '0 var(--s5)',
        background: LEVEL_BG[level],
        borderBottom: visible ? '1px solid var(--separator)' : 'none',
      }}
    >
      <Badge variant={LEVEL_BADGE_VARIANT[level]}>{level}</Badge>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
          color: 'var(--label-secondary)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        MAX DD:{' '}
        <span style={{ color: 'var(--red)' }}>
          {(maxDrawdown * 100).toFixed(2)}%
        </span>
      </span>
      {alertCount > 0 && (
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--label-secondary)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          ALERTS:{' '}
          <span style={{ color: level === 'HIGH' || level === 'CRITICAL' ? 'var(--red)' : 'var(--orange)' }}>
            {alertCount}
          </span>
        </span>
      )}
      <div style={{ flex: 1 }} />
      <KillSwitch />
    </div>
  );
});
