import { Component, type ErrorInfo, type ReactNode } from 'react'
import { API_BASE } from '@/lib/constants'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export function reportError(payload: {
  message: string
  stack?: string
  component_stack?: string
  url: string
}) {
  const body = JSON.stringify({
    ...payload,
    user_agent: navigator.userAgent,
    timestamp: new Date().toISOString(),
  })
  navigator.sendBeacon(
    `${API_BASE}/client-errors`,
    new Blob([body], { type: 'application/json' }),
  )
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportError({
      message: error.message,
      stack: error.stack ?? undefined,
      component_stack: info.componentStack ?? undefined,
      url: window.location.href,
    })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-4 bg-background p-8">
          <h1 className="text-2xl font-bold text-foreground">Something went wrong</h1>
          <p className="max-w-md text-center text-muted-foreground">
            {this.state.error?.message ?? 'An unexpected error occurred.'}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Reload
          </button>
        </div>
      )
    }

    return this.props.children
  }
}

/**
 * Install global handlers for unhandled errors and promise rejections.
 * Call once in main.tsx before rendering.
 */
export function installGlobalErrorReporter() {
  window.addEventListener('error', (event) => {
    reportError({
      message: event.message,
      stack: event.error?.stack,
      url: window.location.href,
    })
  })

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    reportError({
      message: reason instanceof Error ? reason.message : String(reason),
      stack: reason instanceof Error ? reason.stack : undefined,
      url: window.location.href,
    })
  })
}
