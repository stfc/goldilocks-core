import {
  AppShell as MantineAppShell,
  Group,
  SegmentedControl,
  Text,
  Title,
} from '@mantine/core';
import { useRef, useState } from 'react';
import { GuidedView } from '../views/GuidedView/GuidedView';
import { GraphView } from '../views/GraphView/GraphView';

type View = 'guided' | 'graph';

function BrandMark() {
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 28 28"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="14" cy="14" r="12" fill="var(--mantine-color-gold-3)" />
      <circle cx="10" cy="11" r="3" fill="var(--mantine-color-gold-7)" />
      <circle cx="18" cy="11" r="3" fill="var(--mantine-color-gold-7)" />
      <circle cx="14" cy="17" r="3" fill="var(--mantine-color-gold-7)" />
    </svg>
  );
}

/**
 * Application shell: brand header, Guided/Graph switcher, and the active view.
 * Both views read the same tab-lifetime Workspace store, so switching views
 * preserves structure, Intent, Hints, records, failures, and generated output.
 */
export function WorkbenchShell() {
  const [view, setView] = useState<View>('guided');
  const mainRef = useRef<HTMLDivElement | null>(null);

  const switchView = (next: string) => {
    setView(next as View);
    // Move focus into the freshly revealed view so keyboard and screen-reader
    // users are not left behind after a view change.
    requestAnimationFrame(() => mainRef.current?.focus());
  };

  return (
    <MantineAppShell header={{ height: 64 }} padding={{ base: 'md', sm: 'lg' }}>
      <MantineAppShell.Header
        style={{
          borderBottom: '1px solid var(--mantine-color-stone-2)',
          background: 'var(--mantine-color-stone-0)',
        }}
      >
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <BrandMark />
            <div>
              <Title order={1}>Goldilocks</Title>
              <Text size="xs" c="dimmed" lh={1}>
                Workbench
              </Text>
            </div>
          </Group>
          <SegmentedControl
            value={view}
            onChange={switchView}
            data={[
              { label: 'Guided', value: 'guided' },
              { label: 'Graph', value: 'graph' },
            ]}
            aria-label="View"
          />
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Main
        ref={mainRef}
        tabIndex={-1}
        key={view}
        data-view={view}
        className="view-panel"
      >
        {view === 'guided' ? <GuidedView /> : <GraphView />}
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
