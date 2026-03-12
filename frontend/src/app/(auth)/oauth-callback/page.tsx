"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import api from "@/lib/api";
import { setTokens } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";

function OAuthCallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const setAuth = useAuthStore((s) => s.setAuth);

  useEffect(() => {
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");
    const error = params.get("error");

    if (error || !accessToken || !refreshToken) {
      router.replace(`/login?error=${error ?? "oauth_failed"}`);
      return;
    }

    // Store tokens so the API interceptor picks them up
    setTokens(accessToken, refreshToken);

    // Fetch user profile with the new tokens
    api
      .get("/users/me", {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      .then((r) => {
        setAuth(r.data, accessToken, refreshToken);
        router.replace("/dashboard");
      })
      .catch(() => {
        // Couldn't load profile but tokens are stored — proceed anyway
        router.replace("/dashboard");
      });
  }, [params, router, setAuth]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <Loader2 className="h-8 w-8 animate-spin" />
        <p className="text-sm">Signing you in…</p>
      </div>
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <OAuthCallbackInner />
    </Suspense>
  );
}
