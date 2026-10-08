type NativeIntent = {path: string; initial: boolean};

export function redirectSystemPath({path}: NativeIntent): string {
  try {
    const url = new URL(path);
    const isAuthReturn = url.protocol === 'kinetiq:'
      && (url.hostname === 'callback' || url.hostname === 'logout')
      && (url.pathname === '' || url.pathname === '/');

    // AuthSession receives the original Linking event and owns PKCE/code
    // exchange. The router only chooses the screen; it never authenticates
    // from URL parameters or puts authorization codes into navigation state.
    return isAuthReturn ? '/' : path;
  } catch {
    return path;
  }
}
