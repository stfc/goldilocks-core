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
