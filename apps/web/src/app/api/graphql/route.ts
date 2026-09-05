import { NextRequest, NextResponse } from "next/server";

const backendUrl =
  process.env.KINETIQ_BACKEND_GRAPHQL_URL ?? "http://127.0.0.1:8000/graphql/";
const maxBodyBytes = 64 * 1024;

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (origin && !isSameOrigin(origin, request.nextUrl.host)) {
    return NextResponse.json({ errors: [{ message: "Cross-origin request rejected" }] }, { status: 403 });
  }

  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > maxBodyBytes) {
    return NextResponse.json({ errors: [{ message: "GraphQL request is too large" }] }, { status: 413 });
  }

  const headers = new Headers({ "content-type": "application/json" });
  for (const name of ["authorization", "cookie", "x-csrftoken", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const response = await fetch(backendUrl, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return NextResponse.json({ errors: [{ message: "Backend unavailable" }] }, { status: 503 });
  }
}

function isSameOrigin(origin: string, expectedHost: string) {
  try {
    return new URL(origin).host === expectedHost;
  } catch {
    return false;
  }
}
