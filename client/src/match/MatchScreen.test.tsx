import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MatchScreen } from './MatchScreen.tsx';
import type { ScenarioId } from './fixtures/scenarios.ts';

const CONNECT_MS = 700;
const OPPONENT_LOCK_MS = 2200;

/**
 * `fireEvent`, not `userEvent`, throughout this file.
 *
 * The demo is a thing that happens over time, so the whole suite runs on fake
 * timers — and userEvent awaits real timers of its own between events, which
 * never fire while they are faked, so every click hangs until the test times
 * out. fireEvent dispatches synchronously and leaves the clock entirely to
 * `tick`, which is what a timer-driven screen wants anyway.
 */
function tap(name: string | RegExp): void {
  fireEvent.click(screen.getByRole('button', { name }));
}

function tick(ms: number): void {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

function open(scenario: ScenarioId = 'zoneControl') {
  render(<MatchScreen initialScenario={scenario} />);
  tick(CONNECT_MS);
}

describe('the opening demo', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('lands on the delivered plan screen, pre-filled and one tap from locked', () => {
    open();

    expect(screen.getByRole('heading', { name: 'Round 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Choose troops/ })).toHaveTextContent('Emberwright');

    tap('Lock in');

    expect(screen.getByRole('heading', { name: 'Locked in' })).toBeInTheDocument();
  });

  it('shows your troops taking position, and nothing of theirs', () => {
    open();
    tap('Lock in');

    const board = screen.getByRole('img', { name: /Battle at tick/ });

    expect(board.querySelectorAll('.unit.is-yours').length).toBeGreaterThan(0);
    // Not one opponent mark, because their plan is not in the snapshot at all —
    // it is withheld at the session, not merely left undrawn here.
    expect(board.querySelectorAll('.unit.is-theirs')).toHaveLength(0);
  });

  it('starts the battle when the other seat locks in', () => {
    open();
    tap('Lock in');
    tick(OPPONENT_LOCK_MS);

    expect(screen.getByRole('region', { name: /Round 1 battle/ })).toBeInTheDocument();
    const board = screen.getByRole('img', { name: /Battle at tick/ });
    expect(board.querySelectorAll('.unit.is-theirs').length).toBeGreaterThan(0);
  });

  it('keeps both bases and every zone on screen during the battle', () => {
    open();
    tap('Lock in');
    tick(OPPONENT_LOCK_MS + 1000);

    const board = screen.getByRole('img', { name: /Battle at tick/ });
    expect(within(board).getByText('YOUR BASE')).toBeInTheDocument();
    expect(within(board).getByText('THEIR BASE')).toBeInTheDocument();
    expect(within(board).getAllByText(/1000 \/ 1000|\d+ \/ 1000/)).toHaveLength(2);
    for (const zone of ['A', 'B', 'C']) {
      expect(within(board).getByText(new RegExp(`^${zone} · `))).toBeInTheDocument();
    }
  });
});

describe('casting a spell', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function intoBattle() {
    open();
    tap('Lock in');
    tick(OPPONENT_LOCK_MS);
  }

  it('is two taps — the spell, then where it goes', () => {
    intoBattle();

    tap(/Fireball/);
    expect(screen.getByTestId('cast-prompt')).toHaveTextContent('Where should Fireball land?');

    tap('Zone B');
    expect(screen.getByTestId('cast-feedback')).toHaveTextContent('Fireball on Zone B — sent…');

    tick(200);
    expect(screen.getByTestId('cast-feedback')).toHaveTextContent('Fireball on Zone B — landed.');
  });

  it('can be called off before it is aimed', () => {
    intoBattle();

    tap(/Fireball/);
    tap('Cancel');

    expect(screen.queryByTestId('cast-prompt')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Zone B' })).not.toBeInTheDocument();
  });

  it('says what the energy is short by rather than just greying out', () => {
    intoBattle();

    // Energy starts at 3 and Fireball costs 3, so one cast empties the pool.
    tap(/Fireball/);
    tap('Zone B');
    tick(200);

    expect(screen.getByRole('button', { name: /Fireball/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Fireball/ })).toHaveTextContent(
      /needs 3 · you have/,
    );
  });
});

describe('losing the connection', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('says so, keeps the board, and stops taking casts', () => {
    open('dropout');
    tap('Lock in');
    tick(OPPONENT_LOCK_MS);
    tick(160 * 50);

    expect(screen.getByTestId('stale-banner')).toHaveTextContent(/reconnecting/i);
    expect(screen.getByRole('img', { name: /Battle at tick/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Fireball/ })).toBeDisabled();
  });

  it('comes back to wherever the server got to', () => {
    open('dropout');
    tap('Lock in');
    tick(OPPONENT_LOCK_MS);
    tick(160 * 50);

    const abandoned = tickOnScreen();
    tick(6000);

    expect(screen.queryByTestId('stale-banner')).not.toBeInTheDocument();
    expect(tickOnScreen()).toBeGreaterThan(abandoned + 100);
  });
});

function tickOnScreen(): number {
  const label = screen.getByRole('img', { name: /Battle at tick/ }).getAttribute('aria-label');
  return Number(/tick (\d+)/.exec(label ?? '')?.[1] ?? -1);
}

describe('a seat that cannot be claimed', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('explains itself and offers the retry that works', () => {
    open('claimFailure');

    expect(screen.getByTestId('claim-reason')).toHaveTextContent(/seat could not be claimed/i);

    tap('Try again');
    tick(CONNECT_MS);

    expect(screen.getByRole('heading', { name: 'Round 1' })).toBeInTheDocument();
  });
});

describe('the result', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function playOut(scenario: ScenarioId) {
    open(scenario);
    tap('Lock in');
    tick(OPPONENT_LOCK_MS);
    tick(40_000);
  }

  it('calls an ordinary round a round, and says the test stops there', () => {
    playOut('zoneControl');

    expect(screen.getByTestId('result-headline')).toHaveTextContent(/^Round 1 (to|drawn)/);
    expect(screen.getByTestId('result-detail')).toHaveTextContent(/test stops after one round/);
    expect(screen.getByText(/Win three rounds, or destroy the enemy base/)).toBeInTheDocument();
  });

  it('calls a destroyed base the end of the match, not the end of a round', () => {
    playOut('baseDestruction');

    expect(screen.getByTestId('result-headline')).toHaveTextContent('Your base is down — you lose');
    expect(screen.getByTestId('result-detail')).toHaveTextContent(/ends the match immediately/);
    expect(within(screen.getByTestId('result-bases')).getByText('Destroyed')).toBeInTheDocument();
  });

  it('offers a fresh run, and starting one goes back to the top', () => {
    playOut('zoneControl');

    tap('New test');
    expect(screen.getByRole('heading', { name: /Taking your seat/ })).toBeInTheDocument();

    tick(CONNECT_MS);
    expect(screen.getByRole('heading', { name: 'Round 1' })).toBeInTheDocument();
  });
});
