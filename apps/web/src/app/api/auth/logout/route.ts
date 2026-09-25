import { NextResponse } from "next/server";

import { authConfiguration, clearAuthCookies } from "@/lib/auth";

export function GET() {
  try {
    const config = authConfiguration();
    const logout = new URL(`https://${config.domain}/logout`);
    logout.search = new URLSearchParams({
      client_id: config.clientId,
      logout_uri: config.publicOrigin,
    }).toString();
    const response = NextResponse.redirect(logout);
    clearAuthCookies(response);
    return response;
  } catch {
    return NextResponse.json({ error: "Authentication is not configured" }, { status: 503 });
  }
}
