import { useMemo } from 'react';
import { MantineProvider } from '@mantine/core';
import { WorkbenchShell } from './app/AppShell';
import { ErrorBoundary } from './app/ErrorBoundary';
import { theme } from './app/theme';
import { HttpCoreClient } from './client/HttpCoreClient';
import { createWorkspaceStore, type WorkspaceStore } from './store/workspace';
import { WorkspaceProvider } from './store/WorkspaceContext';

export interface AppProps {
  /** Optional injected store (used by tests with a fake CoreClient). */
  store?: WorkspaceStore;
}

export default function App({ store }: AppProps) {
  const resolved = useMemo(
    () => store ?? createWorkspaceStore(new HttpCoreClient()),
    [store],
  );

  return (
    <MantineProvider theme={theme} defaultColorScheme="light">
      <WorkspaceProvider store={resolved}>
        <ErrorBoundary>
          <WorkbenchShell />
        </ErrorBoundary>
      </WorkspaceProvider>
    </MantineProvider>
  );
}
