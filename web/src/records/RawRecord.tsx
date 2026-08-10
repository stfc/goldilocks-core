import { Button, Code, Collapse } from '@mantine/core';
import { useState } from 'react';

/**
 * Advanced disclosure that shows the raw JSON of a record. Owns only its own
 * open/closed state; both Guided and Graph views use it to expose raw Records
 * without a developer tools dependency. No operation state lives here.
 */
export function RawRecord({
  data,
  label,
  id,
}: {
  data: unknown;
  label: string;
  id: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <Button
        variant="subtle"
        size="xs"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={`raw-record-${id}`}
      >
        {label} {open ? 'hide' : 'show'}
      </Button>
      <Collapse expanded={open}>
        <Code block>{JSON.stringify(data, null, 2)}</Code>
      </Collapse>
    </div>
  );
}
