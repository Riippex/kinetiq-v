import { NextRequest, NextResponse } from "next/server";

import { ID_TOKEN_COOKIE, resolveAccessToken, setTokenCookies, tokenClaims } from "@/lib/auth";

export async function GET(request: NextRequest) {
  try {
    const resolved = await resolveAccessToken(request);
    if (!resolved.accessToken) return NextResponse.json({ authenticated: false });
    const claims = tokenClaims(request.cookies.get(ID_TOKEN_COOKIE)?.value);
    const response = NextResponse.json({
      authenticated: true,
      email: typeof claims?.email === "string" ? claims.email : null,
    });
    if (resolved.refreshedTokens) setTokenCookies(response, resolved.refreshedTokens);
    return response;
  } catch {
    return NextResponse.json({ authenticated: false });
  }
}
