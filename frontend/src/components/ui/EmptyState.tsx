import { memo, type ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
  size?: 'sm' | 'md' | 'lg';
}

const SIZE_MAP = {
  sm: { iconSize: 24, titleSize: 12, gap: 4, padding: 12 },
  md: { iconSize: 32, titleSize: 13, gap: 6, padding: 20 },
  lg: { iconSize: 40, titleSize: 14, gap: 8, padding: 32 },
} as const;

export const EmptyState = memo(function EmptyState({ icon, title, description, action, size = 'md' }: EmptyStateProps) {
  const s = SIZE_MAP[size];
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      padding: s.padding, gap: s.gap, color: 'var(--label-tertiary)',
    }}>
      {icon && <div style={{ fontSize: s.iconSize, opacity: 0.5 }}>{icon}</div>}
      <span style={{ fontSize: s.titleSize, color: 'var(--label-secondary)' }}>{title}</span>
      {description && <span style={{ fontSize: 11, color: 'var(--label-quaternary)', textAlign: 'center', maxWidth: 240 }}>{description}</span>}
      {action && (
        <button onClick={action.onClick} style={{
          marginTop: 4, padding: '4px 12px', fontSize: 11,
          background: 'var(--accent-soft)', color: 'var(--accent)',
          border: '1px solid var(--border-accent)', borderRadius: 'var(--r-sm)',
          cursor: 'pointer', fontFamily: 'var(--font-sans)',
        }}>
          {action.label}
        </button>
      )}
    </div>
  );
});
