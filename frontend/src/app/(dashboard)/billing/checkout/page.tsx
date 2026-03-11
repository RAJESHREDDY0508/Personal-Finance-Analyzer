"use client";

import { useMutation } from "@tanstack/react-query";
import { CheckCircle, Brain, Bell, Zap, Shield } from "lucide-react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import api from "@/lib/api";

const FEATURES = [
  { icon: Brain, text: "AI-powered savings suggestions" },
  { icon: Bell, text: "Advanced anomaly detection" },
  { icon: Zap, text: "Unlimited CSV uploads" },
  { icon: Shield, text: "Priority support" },
];

export default function CheckoutPage() {
  const checkout = useMutation({
    mutationFn: () =>
      api.post("/billing/create-checkout-session").then((r) => r.data),
    onSuccess: (data) => {
      if (data?.url) {
        window.location.href = data.url;
      }
    },
    onError: () => toast.error("Unable to start checkout. Please try again."),
  });

  return (
    <div className="max-w-md mx-auto space-y-6 pt-8">
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">
          Upgrade to Premium
        </h1>
        <p className="text-muted-foreground">
          Unlock the full power of AI-driven personal finance.
        </p>
      </div>

      <Card className="border-primary/30 shadow-md">
        <CardHeader className="text-center pb-4">
          <div className="flex items-center justify-center gap-2">
            <CardTitle className="text-4xl font-bold">$9.99</CardTitle>
            <span className="text-muted-foreground mt-2">/month</span>
          </div>
          <Badge className="mx-auto w-fit">Premium Plan</Badge>
          <CardDescription>Cancel anytime, no commitment</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <ul className="space-y-3">
            {FEATURES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-sm">
                <CheckCircle className="h-4 w-4 text-primary shrink-0" />
                {text}
              </li>
            ))}
          </ul>

          <Button
            className="w-full"
            size="lg"
            onClick={() => checkout.mutate()}
            disabled={checkout.isPending}
          >
            {checkout.isPending
              ? "Redirecting to checkout…"
              : "Subscribe — $9.99/month"}
          </Button>

          <p className="text-xs text-center text-muted-foreground">
            Secured by Stripe. Your payment info is never stored on our
            servers.
          </p>
        </CardContent>
      </Card>

      <p className="text-center text-sm text-muted-foreground">
        Questions?{" "}
        <a
          href="mailto:support@financeai.app"
          className="text-primary hover:underline"
        >
          Contact support
        </a>
      </p>
    </div>
  );
}
