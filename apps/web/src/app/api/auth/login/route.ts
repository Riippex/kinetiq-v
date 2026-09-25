import { NextResponse } from "next/server";

import {
  createAuthorizationRequest,
  OAUTH_STATE_COOKIE,
  PKCE_VERIFIER_COOKIE,
  transientCookieOptions,
} from "@/lib/auth";

export function GET() {
  try {
    const authorization = createAuthorizationRequest();
    const response = NextResponse.redirect(authorization.url);
    response.cookies.set(OAUTH_STATE_COOKIE, authorization.state, transientCookieOptions());
    response.cookies.set(PKCE_VERIFIER_COOKIE, authorization.verifier, transientCookieOptions());
    return response;
  } catch {
    return NextResponse.json({ error: "Authentication is not configured" }, { status: 503 });
  }
}
