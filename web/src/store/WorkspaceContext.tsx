// React binding for the vanilla Workspace store.
//
// Holds the store instance in context and exposes typed selectors. Components
// subscribe through `useWorkspace(selector)`; they never receive `setState`.
// The store itself stays in `store/workspace.ts` and is framework-independent.

import { createContext, useContext, type ReactNode } from 'react';
import { useStore } from 'zustand';
import type { WorkspaceState, WorkspaceStore } from './workspace';

const WorkspaceContext = createContext<WorkspaceStore | null>(null);

export function WorkspaceProvider({
  store,
  children,
}: {
  store: WorkspaceStore;
  children: ReactNode;
}) {
  return (
    <WorkspaceContext.Provider value={store}>{children}</WorkspaceContext.Provider>
  );
}

export function useWorkspace<U>(selector: (state: WorkspaceState) => U): U {
  const store = useContext(WorkspaceContext);
  if (store === null) {
    throw new Error('useWorkspace must be used within a WorkspaceProvider');
  }
  return useStore(store, selector);
}

/**
 * Return the store instance itself (no subscription). Use for one-off action
 * sequences where you must read the freshest state after awaiting an action,
 * e.g. reading the just-completed generation output to build an archive.
 */
export function useWorkspaceStore(): WorkspaceStore {
  const store = useContext(WorkspaceContext);
  if (store === null) {
    throw new Error('useWorkspaceStore must be used within a WorkspaceProvider');
  }
  return store;
}
