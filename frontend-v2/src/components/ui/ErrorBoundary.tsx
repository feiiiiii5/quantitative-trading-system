import { Component, type ReactNode, type ErrorInfo } from 'react';

interface Props { children: ReactNode; }
interface State { hasError: boolean; error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error: Error): State { return { hasError: true, error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('[ErrorBoundary]', error, info.componentStack); }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 'var(--u4)', color: 'var(--text-secondary)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-2xl)', fontWeight: 700, color: 'var(--signal-rise)' }}>ERR</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-sm)', color: 'var(--text-muted)', maxWidth: 400, textAlign: 'center' }}>{this.state.error?.message ?? 'Unknown error'}</span>
          <button onClick={() => this.setState({ hasError: false, error: null })} style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-xs)', padding: 'var(--u2) var(--u4)', background: 'var(--bg-raised)', color: 'var(--text-primary)', border: '1px solid var(--border-dim)', borderRadius: 'var(--r-xs)', cursor: 'pointer' }}>RETRY</button>
        </div>
      );
    }
    return this.props.children;
  }
}
