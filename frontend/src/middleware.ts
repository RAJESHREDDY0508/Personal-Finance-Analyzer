/**
 * Next.js middleware — protect dashboard routes.
 * Reads access_token cookie set on login.
 */
import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/", "/login", "/register"];
const AUTH_ROUTES = ["/login", "/register"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const accessToken = request.cookies.get("access_token")?.value;

  // Root → dashboard (or login if not authenticated)
  if (pathname === "/") {
    return NextResponse.redirect(
      new URL(accessToken ? "/dashboard" : "/login", request.url)
    );
  }

  const isAuthRoute = AUTH_ROUTES.some((r) => pathname.startsWith(r));
  const isPublic = PUBLIC_ROUTES.some((r) => pathname === r);

  // Authenticated + visiting login/register → go to dashboard
  if (accessToken && isAuthRoute) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // Unauthenticated + protected route → login
  if (!accessToken && !isPublic) {
    const url = new URL("/login", request.url);
    url.searchParams.set("from", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.png|.*\\.svg).*)",
  ],
};
