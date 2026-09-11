/**
 * Runs two placeholder armies at each other and prints the event stream.
 *
 * Deliberately outside `src/sim/`: this is the one piece that talks to the
 * outside world — argv in, stdout out — and the sim's purity test asserts that
 * nothing like it is reachable from `runBattle`.
 *
 *   npm run sim:demo             # default seed
 *   npm run sim:demo -- --seed 7
 *
 * stdout is the canonical serialisation and nothing else, so two runs can be
 * compared byte for byte. The human-readable summary goes to stderr.
 */
import { THREE_ZONE_MAP, digestBattle, placeholderBattle, runBattle, serializeBattle } from '../sim/index.js';

const DEFAULT_SEED = 20260911;

function readSeed(argv: readonly string[]): number {
  const flag = argv.indexOf('--seed');
  if (flag === -1) return DEFAULT_SEED;

  const raw = argv[flag + 1];
  const seed = Number.parseInt(raw ?? '', 10);
  if (!Number.isInteger(seed)) {
    throw new Error(`--seed needs an integer, got "${raw ?? ''}"`);
  }
  return seed;
}

const seed = readSeed(process.argv.slice(2));
const result = runBattle(THREE_ZONE_MAP, [], placeholderBattle(), seed);

process.stdout.write(`${serializeBattle(result)}\n`);

const defeats = result.events.filter((event) => event.type === 'unitDefeated').length;
const survivors = (side: 'north' | 'south'): number =>
  result.finalState.units.filter((unit) => unit.side === side).length;

process.stderr.write(
  [
    `seed ${seed} · digest ${digestBattle(result)}`,
    `${result.outcome} after ${result.finalState.tick} ticks ` +
      `(${result.finalState.tick / result.config.tickRate}s at ${result.config.tickRate} ticks/s)`,
    `${result.events.length} events, ${defeats} defeats`,
    `survivors: north ${survivors('north')}, south ${survivors('south')}`,
    '',
  ].join('\n'),
);
