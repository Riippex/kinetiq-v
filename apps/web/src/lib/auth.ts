import { createHash, randomBytes } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

export const ACCESS_TOKEN_COOKIE = "kinetiq_access_token";
export const REFRESH_TOKEN_COOKIE = "kinetiq_refresh_token";
export const ID_TOKEN_COOKIE = "kinetiq_id_token";
export const OAUTH_STATE_COOKIE = "kinetiq_oauth_state";
export const PKCE_VERIFIER_COOKIE = "kinetiq_pkce_verifier";

type TokenResponse = {
  access_token: string;
  expires_in: number;
  id_token?: string;
  refresh_token?: string;
  token_type: "Bearer";
};

export function authConfiguration() {
  const domain = requiredEnv("COGNITO_HOSTED_UI_DOMAIN").replace(/^https?:\/\//, "");
  return {
    clientId: requiredEnv("COGNITO_WEB_CLIENT_ID"),
    domain,
    publicOrigin: requiredEnv("KINETIQ_PUBLIC_ORIGIN").replace(/\/$/, ""),
  };
}

export function createAuthorizationRequest() {
  const config = authConfiguration();
  const state = randomBytes(24).toString("base64url");
  const verifier = randomBytes(48).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const callback = `${config.publicOrigin}/api/auth/callback/cognito`;
  const url = new URL(`https://${config.domain}/oauth2/authorize`);
  url.search = new URLSearchParams({
    client_id: config.clientId,
    response_type: "code",
    scope: "openid email profile kinetiq/coach",
    redirect_uri: callback,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  }).toString();
  return { state, verifier, url };
}

export async function exchangeAuthorizationCode(code: string, verifier: string) {
  const config = authConfiguration();
  return requestTokens(
    new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.clientId,
      code,
      code_verifier: verifier,
      redirect_uri: `${config.publicOrigin}/api/auth/callback/cognito`,
    }),
  );
}

export async function resolveAccessToken(request: NextRequest) {
  const accessToken = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  if (accessToken && tokenExpiresAfter(accessToken, 60)) {
    return { accessToken };
  }

  const refreshToken = request.cookies.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) return { accessToken: null };
  const config = authConfiguration();
  const tokens = await requestTokens(
    new URLSearchParams({
      grant_type: "refresh_token",
      client_id: config.clientId,
      refresh_token: refreshToken,
    }),
  );
  return { accessToken: tokens.access_token, refreshedTokens: tokens };
}

export function setTokenCookies(response: NextResponse, tokens: TokenResponse) {
  response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, cookieOptions(tokens.expires_in));
  if (tokens.refresh_token) {
    response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, cookieOptions(30 * 24 * 60 * 60));
  }
  if (tokens.id_token) {
    response.cookies.set(ID_TOKEN_COOKIE, tokens.id_token, cookieOptions(tokens.expires_in));
  }
}

export function clearAuthCookies(response: NextResponse) {
  for (const name of [
    ACCESS_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE,
    ID_TOKEN_COOKIE,
    OAUTH_STATE_COOKIE,
    PKCE_VERIFIER_COOKIE,
  ]) {
    response.cookies.set(name, "", cookieOptions(0));
  }
}

export function transientCookieOptions() {
  return cookieOptions(10 * 60);
}

export function tokenClaims(token: string | undefined) {
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    return JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function requestTokens(parameters: URLSearchParams): Promise<TokenResponse> {
  const { domain } = authConfiguration();
  const response = await fetch(`https://${domain}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: parameters,
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Cognito token exchange failed (${response.status})`);
  const tokens = (await response.json()) as Partial<TokenResponse>;
  if (!tokens.access_token || !tokens.expires_in || tokens.token_type !== "Bearer") {
    throw new Error("Cognito token response is incomplete");
  }
  return tokens as TokenResponse;
}

function tokenExpiresAfter(token: string, seconds: number) {
  const exp = tokenClaims(token)?.exp;
  return typeof exp === "number" && exp > Math.floor(Date.now() / 1000) + seconds;
}

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

function requiredEnv(name: string) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}
