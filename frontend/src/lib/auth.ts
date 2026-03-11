/**
 * Token helpers — keep localStorage and the middleware cookie in sync.
 */

const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
// Access token TTL (match backend JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
const ACCESS_COOKIE_MAX_AGE = 60 * 15; // 15 minutes

export function setTokens(accessToken: string, refreshToken: string) {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  // Cookie lets middleware detect auth without JS
  document.cookie = `access_token=${accessToken}; path=/; max-age=${ACCESS_COOKIE_MAX_AGE}; samesite=lax`;
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  document.cookie = "access_token=; path=/; max-age=0";
}
