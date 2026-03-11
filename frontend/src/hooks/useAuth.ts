"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import api from "@/lib/api";
import { setTokens, clearTokens } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";

interface AuthPayload {
  email: string;
  password: string;
}

interface AuthResponse {
  access_token: string;
  refresh_token: string;
  user: {
    id: string;
    email: string;
    full_name: string | null;
    plan: "free" | "premium";
    health_score: number;
  };
}

export function useLogin() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);

  return useMutation({
    mutationFn: (data: AuthPayload) =>
      api.post<AuthResponse>("/auth/login", data).then((r) => r.data),
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token);
      setAuth(data.user, data.access_token, data.refresh_token);
      router.replace("/dashboard");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Login failed";
      toast.error(msg);
    },
  });
}

export function useRegister() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);

  return useMutation({
    mutationFn: (data: AuthPayload) =>
      api.post<AuthResponse>("/auth/register", data).then((r) => r.data),
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token);
      setAuth(data.user, data.access_token, data.refresh_token);
      router.replace("/dashboard");
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Registration failed";
      toast.error(msg);
    },
  });
}

export function useLogout() {
  const router = useRouter();
  const clearAuth = useAuthStore((s) => s.clearAuth);

  return () => {
    clearTokens();
    clearAuth();
    router.replace("/login");
  };
}
