import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { HttpCoreClient } from '../../client/HttpCoreClient';
import { siCif, siStructureDocument } from '../mocks/fixtures';

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('HttpCoreClient', () => {
  it('loads a structure through the HTTP adapter and maps to the domain type', async () => {
    server.use(
      http.post('*/structure/load', () => HttpResponse.json(siStructureDocument)),
    );
    const client = new HttpCoreClient('http://localhost');
    const document = await client.loadStructure({ content: siCif, format: 'cif' });
    expect(document.formula).toBe('Si8');
    expect(document.lattice.volume).toBeCloseTo(160.191, 2);
  });

  it('maps a structured 4xx envelope to a CoreFailure', async () => {
    server.use(
      http.post(
        '*/structure/load',
        () =>
          HttpResponse.json(
            {
              error: {
                kind: 'invalid_request',
                message: 'Field content is required.',
                status: 422,
                details: { missing: ['content'] },
              },
            },
            { status: 422 },
          ),
        { once: true },
      ),
    );
    const client = new HttpCoreClient('http://localhost');
    await expect(client.loadStructure({ content: '' })).rejects.toMatchObject({
      kind: 'invalid_request',
      message: 'Field content is required.',
      status: 422,
    });
  });

  it('maps a bare FastAPI validation 422 to invalid_request with diagnostics', async () => {
    server.use(
      http.post(
        '*/structure/load',
        () =>
          HttpResponse.json(
            {
              detail: [
                {
                  type: 'string_type',
                  loc: ['body', 'structure', 'content'],
                  msg: 'Input should be a valid string',
                  input: 123,
                },
              ],
            },
            { status: 422 },
          ),
        { once: true },
      ),
    );
    const client = new HttpCoreClient('http://localhost');
    await expect(client.loadStructure({ content: siCif })).rejects.toMatchObject({
      kind: 'invalid_request',
      status: 422,
      message: expect.stringContaining('structure.content'),
    });
  });

  it('maps a network failure to an unavailable CoreFailure', async () => {
    server.use(
      http.post('*/structure/load', () => HttpResponse.error(), { once: true }),
    );
    const client = new HttpCoreClient('http://localhost');
    await expect(client.loadStructure({ content: siCif })).rejects.toMatchObject({
      kind: 'unavailable',
    });
  });
});
