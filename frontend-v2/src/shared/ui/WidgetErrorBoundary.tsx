import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class WidgetErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[WidgetErrorBoundary]', error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="flex items-center justify-center h-full bg-[var(--bg-surface)] border border-[var(--color-critical)]/30 rounded-[var(--radius-md)] p-[var(--space-4)]">
            <div className="text-center">
              <div className="text-[var(--color-critical)] text-[var(--font-size-sm)] mb-1">Widget Error</div>
              <div className="text-[var(--text-muted)] text-[var(--font-size-xs)]">{this.state.error?.message}</div>
              <button
                className="mt-2 text-[var(--text-accent)] text-[var(--font-size-xs)] hover:underline"
                onClick={() => this.setState({ hasError: false, error: null })}
              >
                Retry
              </button>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
