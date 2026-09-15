import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App.tsx';

describe('App', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('opens on the seat claim, then the plan phase', () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: /Taking your seat/ })).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(700));

    expect(screen.getByRole('heading', { name: 'Round 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Lock in' })).toBeInTheDocument();
  });
});
