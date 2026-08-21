"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
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

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="rounded-lg bg-red/10 p-6">
            <h3 className="mb-2 text-sm font-medium text-red">
              Something went wrong
            </h3>
            <pre className="text-xs text-text-secondary">
              {this.state.error?.message}
            </pre>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="mt-3 rounded bg-bg-card px-3 py-1.5 text-xs text-text-secondary hover:text-text"
            >
              Try again
            </button>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
