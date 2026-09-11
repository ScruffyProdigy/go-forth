import cors from 'cors';
import express, { type Express } from 'express';

import { config } from './config.js';

/**
 * Builds the express app without binding a port, so tests can drive it over
 * supertest and `server.ts` stays a three-line entry point.
 */
export function createApp(): Express {
  const app = express();

  app.use(cors({ origin: config.corsAllowedOrigins }));
  app.use(express.json());

  // Liveness. Kubernetes and the JoinQuest integration checks both read this,
  // so it must stay dependency-free — no database, no outbound calls.
  app.get('/healthz', (_req, res) => {
    res.status(200).type('text/plain').send('ok');
  });

  return app;
}
