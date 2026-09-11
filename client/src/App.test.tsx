import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from './App.tsx';

describe('App', () => {
  it('renders the placeholder screen', () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: 'Go Forth!' })).toBeInTheDocument();
  });

  it('names the api the client will talk to', () => {
    render(<App />);

    expect(screen.getByText('http://localhost:3002')).toBeInTheDocument();
  });
});
