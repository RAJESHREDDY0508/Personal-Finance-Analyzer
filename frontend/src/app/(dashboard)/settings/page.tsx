"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Shield, CreditCard } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuthStore } from "@/stores/authStore";
import { useLogout } from "@/hooks/useAuth";
import api from "@/lib/api";

interface ProfileForm {
  full_name: string;
}

interface UserProfile {
  id: string;
  email: string;
  full_name: string | null;
  plan: "free" | "premium";
  health_score: number;
}

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const logout = useLogout();

  const profile = useQuery<UserProfile>({
    queryKey: ["profile"],
    queryFn: () => api.get("/users/me").then((r) => r.data),
  });

  const { register, handleSubmit } = useForm<ProfileForm>({
    values: { full_name: profile.data?.full_name ?? "" },
  });

  const updateProfile = useMutation({
    mutationFn: (data: ProfileForm) =>
      api.patch("/users/me", data).then((r) => r.data),
    onSuccess: (updated) => {
      setUser(updated);
      toast.success("Profile updated");
    },
    onError: () => toast.error("Failed to update profile"),
  });

  return (
    <div className="space-y-6 max-w-xl">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>

      {/* Profile */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Profile</CardTitle>
          <CardDescription>Update your personal details</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <Label>Email</Label>
            <Input value={user?.email ?? ""} disabled />
          </div>
          <form
            onSubmit={handleSubmit((d) => updateProfile.mutate(d))}
            className="space-y-4"
          >
            <div className="space-y-1">
              <Label htmlFor="full_name">Full name</Label>
              <Input
                id="full_name"
                placeholder="Jane Doe"
                {...register("full_name")}
              />
            </div>
            <Button type="submit" disabled={updateProfile.isPending}>
              {updateProfile.isPending ? "Saving…" : "Save changes"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Plan */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <CreditCard className="h-4 w-4" />
            Subscription
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="text-sm">Current plan:</span>
            <Badge
              variant={profile.data?.plan === "premium" ? "default" : "secondary"}
              className="capitalize"
            >
              {profile.data?.plan ?? "free"}
            </Badge>
          </div>
          {profile.data?.plan !== "premium" && (
            <div className="rounded-lg bg-muted/50 p-4 space-y-2">
              <p className="text-sm font-medium flex items-center gap-2">
                <Shield className="h-4 w-4 text-primary" />
                Upgrade to Premium
              </p>
              <p className="text-xs text-muted-foreground">
                Unlock AI savings suggestions, advanced anomaly detection,
                and priority support.
              </p>
              <Button size="sm" onClick={() => { window.location.href = "/billing/checkout"; }}>
                Upgrade — $9.99/month
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Danger zone */}
      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle className="text-base text-destructive">
            Danger Zone
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={logout}>
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
