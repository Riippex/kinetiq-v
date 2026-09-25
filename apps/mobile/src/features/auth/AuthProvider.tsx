import * as AuthSession from 'expo-auth-session';
import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';

WebBrowser.maybeCompleteAuthSession();

const ACCESS_TOKEN_KEY = 'kinetiq.mobile.access-token.v1';
const REFRESH_TOKEN_KEY = 'kinetiq.mobile.refresh-token.v1';
const SESSION_METADATA_KEY = 'kinetiq.mobile.session-metadata.v1';
const cognitoDomain = process.env.EXPO_PUBLIC_COGNITO_DOMAIN;
const clientId = process.env.EXPO_PUBLIC_COGNITO_MOBILE_CLIENT_ID;
const redirectUri = AuthSession.makeRedirectUri({native: 'kinetiq://callback'});
const logoutUri = 'kinetiq://logout';

const discovery: AuthSession.DiscoveryDocument = {
  authorizationEndpoint: `https://${cognitoDomain ?? 'cognito-not-configured.invalid'}/oauth2/authorize`,
  tokenEndpoint: `https://${cognitoDomain ?? 'cognito-not-configured.invalid'}/oauth2/token`,
  revocationEndpoint: `https://${cognitoDomain ?? 'cognito-not-configured.invalid'}/oauth2/revoke`,
};

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

type StoredSession = {
  expiresIn?: number;
  issuedAt: number;
  scope?: string;
  tokenType: AuthSession.TokenType;
};

const secureStoreOptions: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

type AuthContextValue = {
  authorization: string | null;
  error: string | null;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  status: AuthStatus;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({children}: PropsWithChildren) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [session, setSession] = useState<AuthSession.TokenResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refreshInFlight = useRef<Promise<AuthSession.TokenResponse | null> | null>(null);
  const [request, , promptAsync] = AuthSession.useAuthRequest(
    {
      clientId: clientId ?? 'cognito-client-not-configured',
      redirectUri,
      responseType: AuthSession.ResponseType.Code,
      scopes: ['openid', 'email', 'profile', 'kinetiq/coach'],
      usePKCE: true,
    },
    discovery,
  );

  const persistSession = useCallback(async (
    tokens: AuthSession.TokenResponse,
    previousRefreshToken?: string,
  ) => {
    const metadata: StoredSession = {
      expiresIn: tokens.expiresIn,
      issuedAt: tokens.issuedAt,
      scope: tokens.scope,
      tokenType: tokens.tokenType,
    };
    const refreshToken = tokens.refreshToken ?? previousRefreshToken;
    await Promise.all([
      SecureStore.setItemAsync(ACCESS_TOKEN_KEY, tokens.accessToken, secureStoreOptions),
      SecureStore.setItemAsync(SESSION_METADATA_KEY, JSON.stringify(metadata), secureStoreOptions),
      refreshToken
        ? SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken, secureStoreOptions)
        : SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
    ]);
    const hydrated = new AuthSession.TokenResponse({
      ...metadata,
      accessToken: tokens.accessToken,
      refreshToken,
    });
    setSession(hydrated);
    setStatus('authenticated');
    return hydrated;
  }, []);

  const clearSession = useCallback(async () => {
    await Promise.all([
      SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
      SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
      SecureStore.deleteItemAsync(SESSION_METADATA_KEY),
    ]);
    setSession(null);
    setStatus('unauthenticated');
  }, []);

  const refreshSession = useCallback(async (current: AuthSession.TokenResponse) => {
    if (!current.refreshToken || !clientId) {
      await clearSession();
      return null;
    }
    if (refreshInFlight.current) return refreshInFlight.current;

    const operation = AuthSession.refreshAsync(
      {clientId, refreshToken: current.refreshToken},
      discovery,
    )
      .then(tokens => persistSession(tokens, current.refreshToken))
      .catch(async () => {
        await clearSession();
        return null;
      })
      .finally(() => {
        refreshInFlight.current = null;
      });
    refreshInFlight.current = operation;
    return operation;
  }, [clearSession, persistSession]);

  useEffect(() => {
    let active = true;
    Promise.all([
      SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
      SecureStore.getItemAsync(REFRESH_TOKEN_KEY),
      SecureStore.getItemAsync(SESSION_METADATA_KEY),
    ])
      .then(async ([accessToken, refreshToken, metadataValue]) => {
        if (!active || !accessToken || !metadataValue) {
          if (active) setStatus('unauthenticated');
          return;
        }
        const metadata = JSON.parse(metadataValue) as StoredSession;
        const restored = new AuthSession.TokenResponse({
          ...metadata,
          accessToken,
          refreshToken: refreshToken ?? undefined,
        });
        if (restored.shouldRefresh()) {
          await refreshSession(restored);
        } else if (active) {
          setSession(restored);
          setStatus('authenticated');
        }
      })
      .catch(async () => {
        if (active) await clearSession();
      });
    return () => {
      active = false;
    };
  }, [clearSession, refreshSession]);

  useEffect(() => {
    if (!session?.expiresIn) return;
    const refreshAt = (session.issuedAt + session.expiresIn - 60) * 1000;
    const delay = Math.max(refreshAt - Date.now(), 1_000);
    const timer = setTimeout(() => void refreshSession(session), delay);
    return () => clearTimeout(timer);
  }, [refreshSession, session]);

  const signIn = useCallback(async () => {
    if (!cognitoDomain || !clientId) {
      setError('Mobile authentication is not configured for this build.');
      return;
    }
    if (!request?.codeVerifier) {
      setError('Secure sign-in is still preparing. Please try again.');
      return;
    }
    setError(null);
    const result = await promptAsync();
    if (result.type !== 'success') {
      if (result.type === 'error') {
        setError(result.error?.message ?? 'Cognito could not complete sign in.');
      }
      return;
    }
    const code = result.params.code;
    if (!code) {
      setError('The authorization response was incomplete. Please try again.');
      return;
    }

    setStatus('loading');
    try {
      const tokens = await AuthSession.exchangeCodeAsync(
        {clientId, code, redirectUri, extraParams: {code_verifier: request.codeVerifier}},
        discovery,
      );
      await persistSession(tokens);
    } catch {
      setStatus('unauthenticated');
      setError('The authorization code could not be exchanged. Please try again.');
    }
  }, [persistSession, promptAsync, request]);

  const signOut = useCallback(async () => {
    const token = session?.refreshToken ?? session?.accessToken;
    if (token && clientId) {
      await AuthSession.revokeAsync({clientId, token}, discovery).catch(() => false);
    }
    await clearSession();

    if (cognitoDomain && clientId) {
      const url = new URL(`https://${cognitoDomain}/logout`);
      url.search = new URLSearchParams({client_id: clientId, logout_uri: logoutUri}).toString();
      await WebBrowser.openAuthSessionAsync(url.toString(), logoutUri).catch(() => null);
    }
  }, [clearSession, session]);

  const value = useMemo<AuthContextValue>(() => ({
    authorization: session ? `Bearer ${session.accessToken}` : null,
    error,
    signIn,
    signOut,
    status,
  }), [error, session, signIn, signOut, status]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
