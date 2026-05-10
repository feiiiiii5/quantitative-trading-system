import { memo } from 'react';
import type { SignalAction } from '@/types';

const ACTION_CONFIG: Record<SignalAction, { color: string; bg: string }> = {
  BUY: { color: '#FF1744', bg: 'rgba(255,23,68,0.12)' },
  SELL: { color: '#00C853', bg: 'rgba(0,200,83,0.12)' },
  HOLD: { color: 'rgba(255,255,255,0.30)', bg: 'rgba(255,255,255,0.04)' },
};

interface SignalBadgeProps {
  action: SignalAction;
}

export const SignalBadge = memo(function SignalBadge({ action }: SignalBadgeProps) {
  const config = ACTION_CONFIG[action];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase',
      letterSpacing: '0.08em', padding: '2px 8px', borderRadius: '2px',
      color: config.color, background: config.bg,
    }}>
      <span style={{ width: '2px', height: '10px', borderRadius: '1px', background: config.color }} />
      {action}
    </span>
  );
});
