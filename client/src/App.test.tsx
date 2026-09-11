import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from './App.tsx';

describe('App', () => {
  it('opens on the plan phase', () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: 'Round 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Lock in' })).toBeInTheDocument();
  });
});
