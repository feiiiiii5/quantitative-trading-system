import { memo, type CSSProperties } from 'react';

type BadgeVariant = 'buy' | 'sell' | 'hold' | 'rise' | 'fall' | 'info' | 'warn';

interface BadgeProps {
  variant: BadgeVariant;
  children?: string;
  style?: CSSProperties;
}

const VARIANT_MAP: Record<BadgeVariant, { bg: string; color: string; label: string }> = {
  buy: { bg: 'var(--red-soft)', color: 'var(--red)', label: 'BUY' },
  rise: { bg: 'var(--red-soft)', color: 'var(--red)', label: 'RISE' },
  sell: { bg: 'var(--green-soft)', color: 'var(--green)', label: 'SELL' },
  fall: { bg: 'var(--green-soft)', color: 'var(--green)', label: 'FALL' },
  hold: { bg: 'var(--accent-soft)', color: 'var(--accent)', label: 'HOLD' },
  info: { bg: 'var(--accent-soft)', color: 'var(--accent)', label: 'INFO' },
  warn: { bg: 'var(--orange-soft)', color: 'var(--orange)', label: 'WARN' },
};

export const Badge = memo(function Badge({ variant, children, style }: BadgeProps) {
  const config = VARIANT_MAP[variant];

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'var(--font-mono)',
        fontSize: '10px',
        fontWeight: 600,
        letterSpacing: '0.04em',
        padding: '2px 8px',
        borderRadius: 'var(--r-pill)',
        background: config.bg,
        color: config.color,
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {children ?? config.label}
    </span>
  );
});
