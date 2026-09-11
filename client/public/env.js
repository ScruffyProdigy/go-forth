// Local development defaults for `window.env`.
//
// Vite serves public/ at the web root, so `vite dev` gets these values and the
// app has one way to read config in every environment. The build copies this
// file into dist/, where the nginx image's entrypoint
// (client/docker-entrypoint.d/40-env-js.sh) overwrites it at container start
// with the deployed environment's values.
//
// Keep the key set in step with that entrypoint: a name added there and not
// here is undefined in dev, and a name added here and not there silently keeps
// its local value in production.
window.env = {
  GAME_APP_ENV: 'local',
  GAME_API_BASE_URL: 'http://localhost:3002',
  GAME_WS_BASE_URL: '',
  GAME_LOBBY_URL: '',
};
