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
    expect(screen.getByText('DYNAMIC · CHALLENGING')).toBeTruthy();

    fireEvent.press(screen.getByTestId('back-to-preparation'));
    expect(screen.getByTestId('preparation-screen')).toBeTruthy();
    expect(screen.getByTestId('mode-dynamic').props.accessibilityState).toEqual(
      {selected: true},
    );
  });
});
