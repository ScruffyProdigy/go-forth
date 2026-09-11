import request from 'supertest';
import { describe, expect, it } from 'vitest';

import { createApp } from './app.js';

describe('GET /healthz', () => {
  it('returns 200', async () => {
    const response = await request(createApp()).get('/healthz');

    expect(response.status).toBe(200);
    expect(response.text).toBe('ok');
  });
});

describe('unknown routes', () => {
  it('404s rather than falling through to a handler that does not exist', async () => {
    const response = await request(createApp()).get('/not-a-route');

    expect(response.status).toBe(404);
  });
});
