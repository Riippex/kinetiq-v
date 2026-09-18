import 'react-native';
import {fireEvent, render} from '@testing-library/react-native';
import * as React from 'react';

import {App} from '../src/App';

describe('App', () => {
  it('renders the remote-friendly preparation controls', () => {
    const screen = render(<App />);

    expect(screen.getByTestId('preparation-screen')).toBeTruthy();
    expect(screen.getByTestId('mode-normal').props.hasTVPreferredFocus).toBe(
      true,
    );
    expect(screen.getByTestId('mode-normal').props.accessibilityState).toEqual({
      selected: true,
    });
    expect(
      screen.getByTestId('intensity-planned').props.accessibilityState,
    ).toEqual({selected: true});
  });

  it('updates choices and supports forward and back navigation', () => {
    const screen = render(<App />);

    fireEvent.press(screen.getByTestId('mode-dynamic'));
    fireEvent.press(screen.getByTestId('intensity-challenging'));
    fireEvent.press(screen.getByTestId('start-session'));

    expect(screen.getByTestId('ready-screen')).toBeTruthy();
    // `{mode} · {intensity}` renders as three separate Text children
    // (`mode`, the literal ' · ', and `intensity`), not one concatenated
    // string, so `.children[0]` alone only ever contains the first
    // fragment ("DYNAMIC"). toHaveTextContent joins all child text nodes,
    // which is the correct way to assert the full rendered text.
    expect(screen.getByTestId('prepared-summary')).toHaveTextContent(
      'DYNAMIC · CHALLENGING',
    );

    fireEvent.press(screen.getByTestId('back-to-preparation'));
    expect(screen.getByTestId('preparation-screen')).toBeTruthy();
    expect(screen.getByTestId('mode-dynamic').props.accessibilityState).toEqual(
      {selected: true},
    );
  });

  it('navigates to pairing screen and displays pairing code', () => {
    const screen = render(<App />);

    fireEvent.press(screen.getByTestId('pair-display'));
    expect(screen.getByTestId('pairing-screen')).toBeTruthy();
    expect(screen.getByTestId('pairing-code').children[0]).toBe('VEGA-4404');

    fireEvent.press(screen.getByTestId('connect-live-session'));
    expect(screen.getByTestId('live-screen')).toBeTruthy();
    expect(screen.getByTestId('visibility-badge')).toBeTruthy();

    fireEvent.press(screen.getByTestId('back-to-prep-from-live'));
    expect(screen.getByTestId('preparation-screen')).toBeTruthy();
  });
});
