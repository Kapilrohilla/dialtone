import { NextResponse, type NextRequest } from "next/server";

const OPEN = [/^\/sign-in(\/|$)/, /^\/set-password(\/|$)/, /^\/api(\/|$)/, /^\/_next(\/|$)/, /^\/voices(\/|$)/, /^\/favicon\.ico$/];

// First value of a possibly comma-separated (multi-proxy) header.
function firstHeader(request: NextRequest, name: string): string | undefined {
  return request.headers.get(name)?.split(",")[0]?.trim() || undefined;
}

// The origin the browser actually used. Behind a proxy the standalone server's
// request.nextUrl carries the internal host (e.g. localhost:3000), so prefer the
// forwarded / Host headers. A relative Location can't be used: Next's middleware
// adapter parses the Location header with `new URL()` and would throw.
function publicOrigin(request: NextRequest): string {
  const host = firstHeader(request, "x-forwarded-host") ?? firstHeader(request, "host") ?? request.nextUrl.host;
  const fwdProto = firstHeader(request, "x-forwarded-proto");
  const proto = fwdProto === "http" || fwdProto === "https" ? fwdProto : request.nextUrl.protocol.replace(/:$/, "");
  return `${proto}://${host}`;
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (OPEN.some((re) => re.test(pathname)) || request.cookies.has("sessionid")) return NextResponse.next();
  const url = new URL("/sign-in", publicOrigin(request));
  url.search = `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url, 307);
}

export const config = { matcher: "/:path*" };
