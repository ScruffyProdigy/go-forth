/**
 * Runtime config, read from `window.env` (see `public/env.js` and the nginx
 * image's entrypoint). Never `import.meta.env`: a build-time value would pin one
 * built image to whichever environment built it, and the same image has to run
 * in local, staging and production.
 */

export interface GameEnv {
  readonly GAME_APP_ENV?: string;
  readonly GAME_API_BASE_URL?: string;
  readonly GAME_WS_BASE_URL?: string;
  readonly GAME_LOBBY_URL?: string;
}

declare global {
  interface Window {
    env?: GameEnv;
  }
}

export function gameEnv(): GameEnv {
  return typeof window === 'undefined' ? {} : (window.env ?? {});
}

/** Where "return to the Lobby" goes. Empty until a deployment sets it. */
export function lobbyUrl(): string | null {
  const url = gameEnv().GAME_LOBBY_URL;
  return url && url.length > 0 ? url : null;
}
