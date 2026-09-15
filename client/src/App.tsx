/**
 * The client's entry screen.
 *
 * The opening demo (JQ-311) owns the whole flow now: plan, lock in, watch the
 * battle, read the result, leave. It runs on a fixture session — JQ-309 is the
 * real Lobby contract and authoritative realtime session, and when it lands the
 * only thing that changes is which session `MatchScreen` opens.
 */
import { MatchScreen } from './match/MatchScreen.tsx';

export function App() {
  return (
    <main className="plan">
      <MatchScreen />
    </main>
  );
}
