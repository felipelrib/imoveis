import React from 'react';
import { t as translate } from '../i18n/index.js';
import { getActiveLocale } from '../i18n/activeLocale.js';

interface ErrorBoundaryProps {
  children: React.ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
  errorInfo: React.ErrorInfo | null
}

class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(): Partial<ErrorBoundaryState> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    this.setState({ error, errorInfo });
    console.error("ErrorBoundary caught an error", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      const t = (key: string) => translate(getActiveLocale(), key);
      return (
        <div style={{ padding: '24px', background: 'var(--bg-surface)', border: '1px solid var(--accent-rose)', borderRadius: '8px', margin: '24px' }}>
          <h2 style={{ color: 'var(--accent-rose)', marginTop: 0 }}>{t('errors.somethingWrong')}</h2>
          <details style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)', fontSize: '13px' }}>
            {this.state.error && this.state.error.toString()}
            <br />
            {this.state.errorInfo && this.state.errorInfo.componentStack}
          </details>
          <button
            className="btn btn-primary"
            style={{ marginTop: '16px' }}
            onClick={() => window.location.reload()}
          >
            {t('errors.reloadPage')}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
