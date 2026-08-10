import { describe, expect, it } from 'vitest';
import { toCoreFailure, localFailure } from '../../client/failures';

describe('toCoreFailure', () => {
  it('maps a structured envelope preserving kind/message/status/details/raw', () => {
    const failure = toCoreFailure({
      error: {
        kind: 'server_busy',
        message: 'Capacity is full; retry shortly.',
        status: 503,
        details: { retry_after: 5 },
      },
    });
    expect(failure.kind).toBe('server_busy');
    expect(failure.message).toBe('Capacity is full; retry shortly.');
    expect(failure.status).toBe(503);
    expect(failure.details).toEqual({ retry_after: 5 });
    expect(failure.raw).toEqual({
      error: {
        kind: 'server_busy',
        message: 'Capacity is full; retry shortly.',
        status: 503,
        details: { retry_after: 5 },
      },
    });
  });

  it('falls back to unexpected for an unknown kind', () => {
    const failure = toCoreFailure({
      error: { kind: 'mystery', message: 'x', status: 500 },
    });
    expect(failure.kind).toBe('unexpected');
    expect(failure.message).toBe('x');
  });

  it('maps a thrown Error to unavailable with the raw error preserved', () => {
    const error = new Error('fetch failed');
    const failure = toCoreFailure(error);
    expect(failure.kind).toBe('unavailable');
    expect(failure.message).toBe('fetch failed');
    expect(failure.raw).toBe(error);
  });

  it('treats a bare object without an envelope as unavailable', () => {
    const failure = toCoreFailure({ nope: true });
    expect(failure.kind).toBe('unavailable');
    expect(failure.raw).toEqual({ nope: true });
  });

  it('maps a FastAPI validation detail body to invalid_request with diagnostics', () => {
    const failure = toCoreFailure({
      detail: [
        {
          type: 'string_type',
          loc: ['body', 'structure', 'content'],
          msg: 'Input should be a valid string',
          input: 123,
        },
      ],
    });
    expect(failure.kind).toBe('invalid_request');
    expect(failure.status).toBe(422);
    expect(failure.message).toContain('Input should be a valid string');
    expect(failure.message).toContain('structure.content');
    expect(failure.details).toHaveLength(1);
    expect(failure.raw).toMatchObject({ detail: expect.any(Array) });
  });

  it('passes an already-mapped CoreFailure through unchanged (idempotent)', () => {
    // The Workspace store re-normalises a thrown failure; an already-mapped
    // structured failure must not be degraded to opaque `unavailable`.
    const mapped = toCoreFailure({
      error: {
        kind: 'invalid_request',
        message: 'Field content is required.',
        status: 422,
        details: null,
      },
    });
    const again = toCoreFailure(mapped);
    expect(again).toBe(mapped);
    expect(again.kind).toBe('invalid_request');
    expect(again.message).toBe('Field content is required.');
    expect(again.status).toBe(422);
  });

  it('localFailure carries an explicit kind and message', () => {
    const failure = localFailure('unavailable', 'Empty response.');
    expect(failure.kind).toBe('unavailable');
    expect(failure.message).toBe('Empty response.');
    expect(failure.status).toBe(0);
  });
});
