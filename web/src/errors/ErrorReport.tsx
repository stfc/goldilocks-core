import { Alert, Code, Group, Stack, Text } from '@mantine/core';
import type { CoreFailure } from '../client/failures';

const KIND_LABEL: Record<string, string> = {
  invalid_request: 'Invalid request',
  stage_error: 'Core stage error',
  not_found: 'Not found',
  server_busy: 'Server busy',
  unavailable: 'Unavailable',
  unexpected: 'Unexpected error',
};

/**
 * Presents a typed `CoreFailure` with diagnostics. It owns no operation state:
 * callers decide where the report appears and what survives it.
 */
export function ErrorReport({ failure }: { failure: CoreFailure }) {
  const label = KIND_LABEL[failure.kind] ?? 'Failure';
  return (
    <Stack gap="xs">
      <Alert color={failure.kind === 'server_busy' ? 'gold' : 'red'} title={label}>
        <Text size="sm">{failure.message}</Text>
        {failure.status > 0 && (
          <Text size="xs" c="dimmed">
            HTTP {failure.status}
          </Text>
        )}
      </Alert>
      {failure.details !== null && failure.details !== undefined && (
        <Code block>
          {typeof failure.details === 'string'
            ? failure.details
            : JSON.stringify(failure.details, null, 2)}
        </Code>
      )}
      <Group gap="xs">
        <Text size="xs" c="dimmed">
          kind: {failure.kind}
        </Text>
      </Group>
    </Stack>
  );
}
