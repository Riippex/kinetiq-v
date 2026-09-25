import { randomBytes } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

import { resolveAccessToken, setTokenCookies } from "@/lib/auth";

const backendUrl =
  process.env.KINETIQ_BACKEND_GRAPHQL_URL ?? "http://127.0.0.1:8000/graphql/";
const maxBodyBytes = 64 * 1024;

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  const publicHost = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!origin || !publicHost || !isSameOrigin(origin, publicHost)) {
    return NextResponse.json({ errors: [{ message: "Cross-origin request rejected" }] }, { status: 403 });
  }

  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > maxBodyBytes) {
    return NextResponse.json({ errors: [{ message: "GraphQL request is too large" }] }, { status: 413 });
  }

  // Django remains protected by CsrfViewMiddleware. Once this BFF has
  // verified the browser's Origin, it creates a matching cookie/header pair
  // for the server-to-server hop while preserving the user's session cookie.
  const csrfToken = randomBytes(16).toString("hex");
  const headers = new Headers({
    "content-type": "application/json",
    cookie: withCsrfCookie(request.headers.get("cookie"), csrfToken),
    "x-csrftoken": csrfToken,
  });
  for (const name of ["authorization", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const resolved = await resolveAccessToken(request);
    if (resolved.accessToken) headers.set("authorization", `Bearer ${resolved.accessToken}`);
    const response = await fetch(backendUrl, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
    const proxyResponse = new NextResponse(await response.text(), {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
    });
    if (resolved.refreshedTokens) setTokenCookies(proxyResponse, resolved.refreshedTokens);
    return proxyResponse;
  } catch {
    return NextResponse.json({ errors: [{ message: "Backend unavailable" }] }, { status: 503 });
  }
}

function withCsrfCookie(cookieHeader: string | null, token: string) {
  const cookies = (cookieHeader ?? "")
    .split(";")
    .map((cookie) => cookie.trim())
    .filter((cookie) => cookie && !cookie.startsWith("csrftoken="));
  cookies.push(`csrftoken=${token}`);
  return cookies.join("; ");
}

function isSameOrigin(origin: string, expectedHost: string) {
  try {
    return new URL(origin).host === expectedHost;
  } catch {
    return false;
  }
}
