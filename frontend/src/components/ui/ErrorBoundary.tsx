import { Component, type ReactNode, type ErrorInfo } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary]', error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48px 24px',
          background: 'var(--bg-elevated)',
          borderRadius: '12px',
          border: '1px solid rgba(255,23,68,0.3)',
          color: 'var(--label-primary)',
          fontFamily: 'var(--font-sans)',
          gap: '12px',
        }}>
          <span style={{ fontSize: '32px' }}>⚠</span>
          <span style={{ fontSize: '16px', fontWeight: 600, color: '#FF1744' }}>
            组件加载失败
          </span>
          <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.4)', maxWidth: '400px', textAlign: 'center' }}>
            页面渲染遇到错误，请刷新页面重试。如果问题持续存在，请联系技术支持。
          </span>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: '8px',
              padding: '8px 20px',
              borderRadius: '8px',
              border: '1px solid rgba(255,255,255,0.15)',
              background: 'rgba(255,255,255,0.05)',
              color: 'rgba(255,255,255,0.8)',
              cursor: 'pointer',
              fontSize: '13px',
              fontFamily: 'var(--font-sans)',
            }}
          >
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
