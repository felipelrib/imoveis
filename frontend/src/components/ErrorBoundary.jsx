import React from 'react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ error, errorInfo });
    console.error("ErrorBoundary caught an error", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '24px', background: 'var(--bg-surface)', border: '1px solid var(--accent-rose)', borderRadius: '8px', margin: '24px' }}>
          <h2 style={{ color: 'var(--accent-rose)', marginTop: 0 }}>Something went wrong.</h2>
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
            Reload Page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
