import { NextRequest, NextResponse } from "next/server";

import {
  authConfiguration,
  exchangeAuthorizationCode,
  OAUTH_STATE_COOKIE,
  PKCE_VERIFIER_COOKIE,
  setTokenCookies,
} from "@/lib/auth";

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  const expectedState = request.cookies.get(OAUTH_STATE_COOKIE)?.value;
  const verifier = request.cookies.get(PKCE_VERIFIER_COOKIE)?.value;
  if (!code || !state || !expectedState || state !== expectedState || !verifier) {
    return NextResponse.json({ error: "Invalid OAuth callback" }, { status: 400 });
  }

  try {
    const tokens = await exchangeAuthorizationCode(code, verifier);
    const response = NextResponse.redirect(new URL("/", authConfiguration().publicOrigin));
    setTokenCookies(response, tokens);
    response.cookies.delete(OAUTH_STATE_COOKIE);
    response.cookies.delete(PKCE_VERIFIER_COOKIE);
    return response;
  } catch {
    return NextResponse.json({ error: "Unable to complete sign in" }, { status: 502 });
  }
}
