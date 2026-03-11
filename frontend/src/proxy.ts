/**
 * Next.js middleware — protect dashboard routes.
 * Redirects unauthenticated users to /login.
 * Redirects authenticated users away from /login and /register.
 */
import { NextRequest, NextResponse } from "next/server";

const PUBLIC_ROUTES = ["/", "/login", "/register", "/forgot-password"];
const AUTH_ROUTES = ["/login", "/register", "/forgot-password"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const accessToken = request.cookies.get("access_token")?.value;

  const isPublic = PUBLIC_ROUTES.some((route) => pathname === route);
  const isAuthRoute = AUTH_ROUTES.some((route) => pathname.startsWith(route));

  // Authenticated user trying to access login/register → redirect to dashboard
  if (accessToken && isAuthRoute) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // Unauthenticated user trying to access protected route → redirect to login
  if (!accessToken && !isPublic) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.png|.*\\.svg).*)",
  ],
};
