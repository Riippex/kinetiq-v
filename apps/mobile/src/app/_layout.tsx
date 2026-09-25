import { DarkTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import {AuthProvider} from '../features/auth/AuthProvider';

export default function RootLayout() {
  return (
    <AuthProvider>
      <ThemeProvider value={DarkTheme}>
        <Stack screenOptions={{headerShown: false}} />
        <StatusBar style="light" />
      </ThemeProvider>
    </AuthProvider>
  );
}
