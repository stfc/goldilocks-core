// Raw record disclosure.
//
// Renders any serializable record as formatted JSON with copy and download
// controls, so raw Records stay available without developer tools. It owns no
// operation state — callers choose where it appears and what it labels.

import { Button, Code, Group, UnstyledButton, Text } from '@mantine/core';
import {
  IconChevronDown,
  IconChevronRight,
  IconClipboard,
  IconDownload,
} from '@tabler/icons-react';
import { useRef, useState } from 'react';

/**
 * Clipboard seam so tests can assert copy without jsdom's volatile Clipboard
 * API (which jsdom replaces with its own object during rendering).
 */
export const clipboard = {
  async write(text: string): Promise<void> {
    await navigator.clipboard.writeText(text);
  },
};

export interface RawJsonProps {
  /** Stable name used for the download filename, e.g. `analysis`. */
  name: string;
  /** The serializable record to disclose. */
  value: unknown;
}

function download(name: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${name}-record.json`;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** A disclosure showing formatted raw JSON with copy and download controls. */
export function RawJson({ name, value }: RawJsonProps) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const json = JSON.stringify(value, null, 2);

  const handleCopy = async () => {
    await clipboard.write(json);
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div>
      <UnstyledButton
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={`raw-${name}`}
        w="100%"
      >
        <Group gap={4} wrap="nowrap">
          {open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
          <Text size="xs" c="dimmed">
            Raw {name}
          </Text>
        </Group>
      </UnstyledButton>
      {open && (
        <div id={`raw-${name}`}>
          <Code block mt="xs" mah={260} style={{ overflow: 'auto' }}>
            <pre style={{ margin: 0 }}>{json}</pre>
          </Code>
          <Group mt="xs" gap="xs">
            <Button
              variant="subtle"
              size="compact-xs"
              leftSection={<IconClipboard size={14} />}
              onClick={() => void handleCopy()}
            >
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button
              variant="subtle"
              size="compact-xs"
              leftSection={<IconDownload size={14} />}
              onClick={() => download(name, json)}
            >
              Download JSON
            </Button>
          </Group>
        </div>
      )}
    </div>
  );
}
