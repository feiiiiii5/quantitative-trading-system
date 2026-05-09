import { cn } from '@/shared/lib/cn';

interface BadgeProps {
  variant?: 'success' | 'warning' | 'danger' | 'neutral' | 'info';
  pulse?: boolean;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ variant = 'neutral', pulse = false, children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-1.5 py-0.5 text-[var(--font-size-xs)] font-medium rounded-[var(--radius-sm)] uppercase tracking-wider',
        {
          'bg-[var(--color-bid)]/15 text-[var(--color-bid)]': variant === 'success',
          'bg-[var(--color-warning)]/15 text-[var(--color-warning)]': variant === 'warning',
          'bg-[var(--color-critical)]/15 text-[var(--color-critical)]': variant === 'danger',
          'bg-[var(--color-neutral)]/15 text-[var(--color-neutral)]': variant === 'neutral',
          'bg-[var(--text-accent)]/15 text-[var(--text-accent)]': variant === 'info',
        },
        className
      )}
    >
      {pulse && (
        <span
          className={cn('w-1.5 h-1.5 rounded-full', {
            'bg-[var(--color-bid)] pulse-dot': variant === 'success',
            'bg-[var(--color-warning)] pulse-dot': variant === 'warning',
            'bg-[var(--color-critical)] pulse-dot': variant === 'danger',
            'bg-[var(--color-neutral)]': variant === 'neutral',
            'bg-[var(--text-accent)]': variant === 'info',
          })}
        />
      )}
      {children}
    </span>
  );
}
