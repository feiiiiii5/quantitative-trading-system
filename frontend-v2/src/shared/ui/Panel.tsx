import { cn } from '@/shared/lib/cn';

interface PanelProps {
  title: string;
  accent?: 'bid' | 'ask' | 'accent' | 'neutral';
  className?: string;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
}

export function Panel({ title, accent = 'neutral', className, headerRight, children }: PanelProps) {
  return (
    <div
      className={cn(
        'flex flex-col bg-[var(--bg-surface)] border border-[var(--bg-border)] rounded-[var(--radius-lg)] overflow-hidden h-full',
        className
      )}
    >
      <div
        className={cn(
          'flex items-center justify-between px-[var(--space-3)] py-[var(--space-2)] border-b border-[var(--bg-border)]',
          {
            'border-l-2 border-l-[var(--color-bid)]': accent === 'bid',
            'border-l-2 border-l-[var(--color-ask)]': accent === 'ask',
            'border-l-2 border-l-[var(--text-accent)]': accent === 'accent',
          }
        )}
      >
        <span className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-[0.1em] font-medium">
          {title}
        </span>
        {headerRight}
      </div>
      <div className="flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
