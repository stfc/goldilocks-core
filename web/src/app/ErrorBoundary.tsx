import { Alert, Stack, Text } from '@mantine/core';
import { Component, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Application-shell error boundary, reserved for unrecoverable rendering
 * failures. Operation failures are handled in their local modules (ErrorReport,
 * per-op store failures) and must never reach this boundary.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  render() {
    if (this.state.error !== null) {
      return (
        <Stack align="center" justify="center" p="xl" mih="60vh">
          <Alert color="red" title="Something went wrong" w="100%" maw={560}>
            <Text size="sm">
              The application shell could not render. This is an unexpected failure;
              your workspace state has not been discarded.
            </Text>
            <Text size="xs" c="dimmed" mt="xs">
              {this.state.error.message}
            </Text>
          </Alert>
        </Stack>
      );
    }
    return this.props.children;
  }
}
