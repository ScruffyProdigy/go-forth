/**
 * The one piece of the match layer that touches the wall clock (JQ-311).
 *
 * A fixture session is a thing that happens *over time* — it connects, the other
 * seat locks in, ticks arrive, the connection drops and comes back. Testing that
 * against real timers means either sleeping in tests or asserting nothing, so the
 * timer is an argument: `manualClock` lets a test say "now 900 ms have passed"
 * and get the same sequence a phone would see, instantly and deterministically.
 */

export interface Clock {
  /** Schedules `run` and returns a handle that `clear` cancels. */
  after(ms: number, run: () => void): number;
  clear(handle: number): void;
}

export const realClock: Clock = {
  after: (ms, run) => window.setTimeout(run, ms),
  clear: (handle) => window.clearTimeout(handle),
};

export interface ManualClock extends Clock {
  /** Runs everything scheduled within the next `ms`, in due order. */
  advance(ms: number): void;
  /** Milliseconds elapsed since the clock was created. */
  readonly now: number;
  readonly pending: number;
}

interface Scheduled {
  readonly handle: number;
  readonly dueAt: number;
  readonly run: () => void;
}

export function manualClock(): ManualClock {
  let now = 0;
  let nextHandle = 1;
  let scheduled: Scheduled[] = [];

  return {
    after(ms, run) {
      const handle = nextHandle++;
      scheduled.push({ handle, dueAt: now + ms, run });
      return handle;
    },
    clear(handle) {
      scheduled = scheduled.filter((entry) => entry.handle !== handle);
    },
    advance(ms) {
      const until = now + ms;
      // Re-read `scheduled` every pass: a callback may schedule the next one,
      // which is exactly how the fixture's tick loop advances.
      for (;;) {
        const due = scheduled
          .filter((entry) => entry.dueAt <= until)
          .sort((a, b) => a.dueAt - b.dueAt || a.handle - b.handle)[0];
        if (!due) break;
        scheduled = scheduled.filter((entry) => entry.handle !== due.handle);
        now = due.dueAt;
        due.run();
      }
      now = until;
    },
    get now() {
      return now;
    },
    get pending() {
      return scheduled.length;
    },
  };
}
