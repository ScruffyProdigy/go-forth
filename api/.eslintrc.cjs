/* ESLint config for the game API (TypeScript, Node ESM). */
module.exports = {
  root: true,
  env: {
    node: true,
    es2022: true,
  },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
  },
  plugins: ['@typescript-eslint'],
  extends: ['eslint:recommended', 'plugin:@typescript-eslint/recommended'],
  rules: {
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_', ignoreRestSiblings: true },
    ],
  },
  overrides: [
    {
      // The sim replays byte-identically from its seed, in this process and in a
      // fresh one (JQ-286). `Math.random` would silently break that, so it is an
      // error here rather than a review comment. The sim draws from `sim/rng.ts`.
      //
      // `sim/purity.test.ts` enforces the rest of the seam — no node: imports,
      // no wall clock, nothing reachable outside `sim/` — by walking the import
      // graph, which is more than a lint rule can see.
      files: ['src/sim/**/*.ts'],
      rules: {
        'no-restricted-properties': [
          'error',
          {
            object: 'Math',
            property: 'random',
            message: 'The sim must be deterministic: draw from the seeded PRNG in sim/rng.ts.',
          },
        ],
      },
    },
  ],
  ignorePatterns: ['dist/', 'node_modules/', '*.config.ts'],
};
