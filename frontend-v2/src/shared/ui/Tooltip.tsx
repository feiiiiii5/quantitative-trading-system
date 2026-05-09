import { useState } from 'react';
import { cn } from '@/shared/lib/cn';

interface TooltipProps {
  content: string;
  children: React.ReactNode;
  className?: string;
}

export function Tooltip({ content, children, className }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  return (
    <div
      className="relative inline-flex"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {children}
      {visible && (
        <div
          className={cn(
            'absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 text-[var(--font-size-xs)] text-[var(--text-primary)] bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] whitespace-nowrap z-50 pointer-events-none',
            className
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
}
