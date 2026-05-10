import { memo } from 'react';
import type { SignalAction } from '@/types';

const ACTION_CONFIG: Record<SignalAction, { color: string; bg: string }> = {
  BUY: { color: '#D4584A', bg: 'rgba(212,88,74,0.06)' },
  SELL: { color: '#4E9E6E', bg: 'rgba(78,158,110,0.06)' },
  HOLD: { color: '#5E5854', bg: 'rgba(255,255,255,0.03)' },
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
