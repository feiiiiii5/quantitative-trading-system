import { forwardRef } from 'react';
import { cn } from '@/shared/lib/cn';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', className, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center font-medium transition-colors focus:outline-none focus:ring-1 focus:ring-[var(--text-accent)] disabled:opacity-50 disabled:pointer-events-none',
          {
            'bg-[var(--text-accent)] text-[var(--bg-base)] hover:opacity-90': variant === 'primary',
            'bg-[var(--bg-elevated)] text-[var(--text-primary)] border border-[var(--bg-border)] hover:bg-[var(--bg-highlight)]': variant === 'secondary',
            'bg-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-highlight)]': variant === 'ghost',
            'bg-[var(--color-critical)] text-white hover:opacity-90': variant === 'danger',
          },
          {
            'h-6 px-2 text-[var(--font-size-xs)] rounded-[var(--radius-sm)]': size === 'sm',
            'h-8 px-3 text-[var(--font-size-sm)] rounded-[var(--radius-md)]': size === 'md',
            'h-10 px-4 text-[var(--font-size-md)] rounded-[var(--radius-md)]': size === 'lg',
          },
          className
        )}
        {...props}
      >
        {children}
      </button>
    );
  }
);

Button.displayName = 'Button';
