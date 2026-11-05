import { NextResponse, type NextRequest } from "next/server";

const OPEN = [/^\/sign-in(\/|$)/, /^\/set-password(\/|$)/, /^\/api(\/|$)/, /^\/_next(\/|$)/, /^\/voices(\/|$)/, /^\/favicon\.ico$/];

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (OPEN.some((re) => re.test(pathname)) || request.cookies.has("sessionid")) return NextResponse.next();
  const url = request.nextUrl.clone();
  url.pathname = "/sign-in";
  url.search = `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url, 307);
}

export const config = { matcher: "/:path*" };
