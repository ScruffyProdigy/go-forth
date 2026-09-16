import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { resolvePlanLocally } from '../match/fixtures/resolvePlan.ts';
import { PlanScreen } from './PlanScreen.tsx';
import { starterMirrorRound1 } from './fixtures/starterMirror.ts';
import { planReducer } from './planReducer.ts';
import type { PlanState } from './types.ts';

/**
 * Tap a mage's card to field or unfield it. Scoped to the card because a round
 * at the cap has both a mage card and a Customise button carrying that name.
 */
async function unfield(
  user: ReturnType<typeof userEvent.setup>,
  mageId: string,
): Promise<void> {
  const card = screen.getByTestId(`mage-${mageId}`);
  await user.click(within(card).getByRole('button', { pressed: true }));
}

describe('a round with no changes', () => {
  it('is one tap to lock in', async () => {
    const user = userEvent.setup();
    const onLockIn = vi.fn();
    render(<PlanScreen onLockIn={onLockIn} />);

    // One tap. Not "open three steps and tap Next three times".
    await user.click(screen.getByRole('button', { name: 'Lock in' }));

    expect(onLockIn).toHaveBeenCalledTimes(1);
    expect(onLockIn.mock.calls[0][0]).toEqual(starterMirrorRound1());
  });

  it('shows the pre-filled plan on the hub before that tap', () => {
    render(<PlanScreen />);

    expect(screen.getByRole('button', { name: /Choose troops/ })).toHaveTextContent('Emberwright');
    expect(screen.getByRole('button', { name: /Choose spells/ })).toHaveTextContent('Fireball');
    expect(screen.getByRole('button', { name: /Give orders/ })).toHaveTextContent('Hold A');
  });
});

describe('resonance', () => {
  it('is the headline on the hub, and moves as mages are fielded', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    expect(screen.getByTestId('resonance-headline')).toHaveTextContent('FIRE 3');
    expect(screen.getByTestId('resonance-headline')).toHaveTextContent('PAR');

    await user.click(screen.getByRole('button', { name: /Choose troops/ }));
    await unfield(user, 'ashenWarden');

    // Live, on the step itself — the decision and its consequence together.
    expect(screen.getByTestId('resonance-headline')).toHaveTextContent('FIRE 2');
    expect(screen.getByTestId('resonance-headline')).toHaveTextContent('BELOW PAR');
  });

  it('shows support capacity filling, and names what is unsupported', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    expect(screen.getByTestId('support-capacity')).toHaveTextContent('7/7');

    await user.click(screen.getByRole('button', { name: /Choose troops/ }));
    await user.click(screen.getByRole('button', { name: /Customise Emberwright/ }));
    await user.click(screen.getAllByRole('button', { name: 'Remove' })[0]);
    await user.click(screen.getByRole('button', { name: 'Back' }));

    expect(screen.getByTestId('support-capacity')).toHaveTextContent('6/7');
    expect(screen.getByTestId('support-capacity')).toHaveTextContent('1 unsupported');
  });
});

describe('the board', () => {
  it('can be looked at from inside a step without losing the step', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    await user.click(screen.getByRole('button', { name: /Give orders/ }));
    expect(screen.getByRole('group', { name: /Order for Emberwright/ })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Board' }));
    expect(screen.getByTestId('step-board')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /board position/ })).toBeInTheDocument();
    // Still in the step: its header and its Next are where they were.
    expect(screen.getByRole('heading', { name: 'Give orders' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.getByRole('group', { name: /Order for Emberwright/ })).toBeInTheDocument();
  });

  it('keeps edits made before the look', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    await user.click(screen.getByRole('button', { name: /Give orders/ }));
    const emberwright = screen.getByRole('group', { name: /Order for Emberwright/ });
    await user.click(within(emberwright).getByRole('button', { name: 'Push enemy base' }));

    await user.click(screen.getByRole('button', { name: 'Board' }));
    await user.click(screen.getByRole('button', { name: 'Done' }));

    expect(
      within(screen.getByRole('group', { name: /Order for Emberwright/ })).getByRole('button', {
        name: 'Push enemy base',
      }),
    ).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('fold depth', () => {
  it('leaves out a step whose decision does not exist yet', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    await user.click(screen.getByRole('button', { name: /Choose troops/ }));
    await unfield(user, 'pyreMagus');
    await unfield(user, 'ashenWarden');
    await user.click(screen.getByRole('button', { name: 'Back' }));

    // One troop left: there is nothing to distribute, so orders is absent
    // rather than shown as an empty list.
    expect(screen.queryByRole('button', { name: /Give orders/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Choose troops/ })).toBeInTheDocument();
  });
});

describe('spell slots', () => {
  it('flags a slot that a troop edit invalidated', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    await user.click(screen.getByRole('button', { name: /Choose troops/ }));
    await unfield(user, 'ashenWarden');
    await user.click(screen.getByRole('button', { name: 'Back' }));

    expect(screen.getByRole('button', { name: /Choose spells/ })).toHaveTextContent(
      'NEEDS REPLACEMENT',
    );

    await user.click(screen.getByRole('button', { name: /Choose spells/ }));
    expect(screen.getByTestId('spell-slot-1')).toHaveTextContent('NEEDS REPLACEMENT');
  });

  it('keeps an ineligible spell visible with its reason', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    await user.click(screen.getByRole('button', { name: /Choose troops/ }));
    await unfield(user, 'ashenWarden');
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: /Choose spells/ }));

    expect(screen.getByText('needs a fielded Guardian mage')).toBeInTheDocument();
    expect(screen.getByText('Cinder Veil')).toBeInTheDocument();
  });
});

describe('no hard timer', () => {
  it('renders no countdown anywhere in the phase', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    const countdown = /\b\d+\s*(s|sec|seconds?)\b|remaining|time left|countdown/i;
    expect(document.body.textContent).not.toMatch(countdown);

    await user.click(screen.getByRole('button', { name: 'Lock in' }));
    expect(document.body.textContent).not.toMatch(countdown);
  });

  it('fills the wait with the troops taking position, not a spinner', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    await user.click(screen.getByRole('button', { name: 'Lock in' }));

    expect(screen.getByRole('heading', { name: 'Locked in' })).toBeInTheDocument();
    expect(screen.getByText('Your troops are taking position.')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /board position/ })).toBeInTheDocument();
  });

  it('lets a player who locked in go back and change the plan', async () => {
    const user = userEvent.setup();
    render(<PlanScreen />);

    await user.click(screen.getByRole('button', { name: 'Lock in' }));
    await user.click(screen.getByRole('button', { name: 'Change the plan' }));

    expect(screen.getByRole('button', { name: 'Lock in' })).toBeInTheDocument();
  });
});

describe('the opponent', () => {
  it("shows last round's sighting on the map, and nothing live", () => {
    const withSighting: PlanState = {
      ...planReducer(starterMirrorRound1(), { type: 'setOrder', mageId: 'emberwright', order: { kind: 'hold', zone: 'A' } }),
      round: 2,
      opponentLastKnown: [{ zone: 'A', mages: 2, summons: 5 }],
    };

    render(<PlanScreen initialPlan={withSighting} />);

    expect(screen.getByText('last seen 2m · 5s')).toBeInTheDocument();
  });
});

/**
 * JQ-311 adaptations. The plan screen stops being the authority on what a plan
 * means and starts asking — and refuses to lock one in that the answer says is
 * invalid.
 */
describe('a resolved plan', () => {
  it('shows the resolved cost, effect and the mages making it so', async () => {
    const user = userEvent.setup();
    render(<PlanScreen resolve={resolvePlanLocally} />);

    await user.click(screen.getByRole('button', { name: /Choose spells/ }));

    // Emberwright and Pyre Magus are both Evocation, and Emberwright is also
    // Reckless: three contributions, and the effect line says what they add to.
    const contributors = screen.getByTestId('contributors-fireball');
    expect(contributors).toHaveTextContent('Emberwright (Evocation)');
    expect(contributors).toHaveTextContent('Emberwright (Reckless)');
    expect(contributors).toHaveTextContent('Pyre Magus (Evocation)');
    // Two Evocation mages raise the damage, one Reckless mage the radius —
    // separately, each on its own curve, which is JQ-297's whole point.
    expect(
      screen.getByText(/damage amount 40 \(\+20 from 2 Evocation mages\); radius 45 \(\+5 from 1 Reckless mage\)/),
    ).toBeInTheDocument();
  });

  it('updates the moment the troops change', async () => {
    const user = userEvent.setup();
    render(<PlanScreen resolve={resolvePlanLocally} />);

    await user.click(screen.getByRole('button', { name: /Choose troops/ }));
    await unfield(user, 'pyreMagus');
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: /Choose spells/ }));

    expect(screen.getByTestId('contributors-fireball')).not.toHaveTextContent('Pyre Magus');
    // Benching Pyre Magus drops Evocation to one and takes 10 off the damage.
    // The radius is untouched: he was never Reckless.
    expect(
      screen.getByText(/damage amount 30 \(\+10 from 1 Evocation mage\); radius 45 \(\+5 from 1 Reckless mage\)/),
    ).toBeInTheDocument();
  });

  it('refuses lock-in while a slot holds a spell the plan no longer grants', async () => {
    const user = userEvent.setup();
    render(<PlanScreen resolve={resolvePlanLocally} />);

    expect(screen.getByRole('button', { name: 'Lock in' })).toBeEnabled();

    await user.click(screen.getByRole('button', { name: /Choose troops/ }));
    await unfield(user, 'ashenWarden');
    await user.click(screen.getByRole('button', { name: 'Back' }));

    // Refused here, on the screen that can fix it — not after lock-in at world
    // creation, which is the shape of JQ-304.
    expect(screen.getByRole('button', { name: 'Lock in' })).toBeDisabled();
    expect(screen.getByTestId('lock-blockers')).toHaveTextContent(
      'Spell 2 — Flame Ward needs Ashen Warden fielded.',
    );
  });

  it('allows it again once the slot is cleared', async () => {
    const user = userEvent.setup();
    render(<PlanScreen resolve={resolvePlanLocally} />);

    await user.click(screen.getByRole('button', { name: /Choose troops/ }));
    await unfield(user, 'ashenWarden');
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('button', { name: /Choose spells/ }));
    await user.click(within(screen.getByTestId('spell-slot-1')).getByRole('button', { name: 'Clear' }));
    await user.click(screen.getByRole('button', { name: 'Back' }));

    expect(screen.getByRole('button', { name: 'Lock in' })).toBeEnabled();
    expect(screen.queryByTestId('lock-blockers')).not.toBeInTheDocument();
  });
});
