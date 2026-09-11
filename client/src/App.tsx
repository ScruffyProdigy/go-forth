/**
 * The client's entry screen.
 *
 * The plan phase (JQ-293) is the first real surface to land. It runs on a local
 * fixture rather than the server: the plan -> sim contract is still open (orders
 * and placement are JQ-287, the spell loadout is JQ-297), and the battle screen
 * is JQ-190/JQ-294.
 */
import { PlanScreen } from './plan/PlanScreen.tsx';

export function App() {
  return (
    <main className="plan">
      <PlanScreen />
    </main>
  );
}
