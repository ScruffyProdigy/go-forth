/**
 * Process configuration, read once at import time.
 *
 * Everything here has a working default, so a clean checkout runs without a
 * `.env`. `.env.example` documents the same names and is the file to keep in
 * step when one is added.
 */
import 'dotenv/config';

/** Offset from rpslr's 3001 and the Lobby's 8080 so all three can run at once. */
const DEFAULT_API_PORT = 3002;

/** Lobby dev origin (5173) and this game's own client (5175). */
const DEFAULT_CORS_ORIGINS = [
  'http://localhost:5173',
  'http://127.0.0.1:5173',
  'http://localhost:5175',
  'http://127.0.0.1:5175',
];

function readPort(): number {
  const raw = process.env.API_PORT;
  if (!raw) return DEFAULT_API_PORT;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed <= 0 || parsed > 65535) {
    throw new Error(`API_PORT must be a port number between 1 and 65535, got "${raw}"`);
  }
  return parsed;
}

function readCorsOrigins(): string[] {
  const raw = process.env.CORS_ALLOWED_ORIGINS;
  if (!raw) return DEFAULT_CORS_ORIGINS;
  const origins = raw
    .split(',')
    .map((origin) => origin.trim())
    .filter((origin) => origin.length > 0);
  return origins.length > 0 ? origins : DEFAULT_CORS_ORIGINS;
}

export const config = {
  apiPort: readPort(),
  corsAllowedOrigins: readCorsOrigins(),
} as const;
