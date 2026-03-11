"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Lightbulb, X } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import api from "@/lib/api";

interface AnomalyTransaction {
  id: string;
  date: string;
  description: string;
  amount: number;
  anomaly_reason: string | null;
  anomaly_score: number | null;
  category: string | null;
}

interface Suggestion {
  id: string;
  suggestion_type: string;
  category: string | null;
  description: string;
  estimated_savings: number | null;
  dismissed: boolean;
}

export default function AlertsPage() {
  const qc = useQueryClient();

  const anomalies = useQuery<AnomalyTransaction[]>({
    queryKey: ["anomalies"],
    queryFn: () =>
      api.get("/transactions/?is_anomaly=true&limit=50").then((r) => r.data),
  });

  const suggestions = useQuery<{ suggestions: Suggestion[]; total: number }>({
    queryKey: ["suggestions"],
    queryFn: () => api.get("/suggestions/").then((r) => r.data),
    retry: false,           // premium-only — 402 means no access
  });

  const dismiss = useMutation({
    mutationFn: (id: string) =>
      api.post(`/suggestions/${id}/dismiss`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["suggestions"] });
      toast.success("Suggestion dismissed");
    },
  });

  const generate = useMutation({
    mutationFn: () => api.post("/suggestions/generate").then((r) => r.data),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["suggestions"] });
      toast.success(`Generated ${d.generated} suggestions`);
    },
    onError: () =>
      toast.error("Suggestions require a Premium subscription"),
  });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Alerts</h1>

      <Tabs defaultValue="anomalies">
        <TabsList>
          <TabsTrigger value="anomalies" className="gap-2">
            <AlertTriangle className="h-4 w-4" />
            Anomalies
            {(anomalies.data?.length ?? 0) > 0 && (
              <Badge variant="destructive" className="ml-1 text-xs">
                {anomalies.data?.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="suggestions" className="gap-2">
            <Lightbulb className="h-4 w-4" />
            Suggestions
          </TabsTrigger>
        </TabsList>

        {/* Anomalies tab */}
        <TabsContent value="anomalies">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Flagged Transactions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {anomalies.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : !anomalies.data?.length ? (
                <p className="text-sm text-muted-foreground">
                  No anomalies detected. Great job!
                </p>
              ) : (
                anomalies.data.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-start justify-between rounded-lg border p-3 gap-4"
                  >
                    <div className="min-w-0 space-y-1">
                      <p className="text-sm font-medium truncate">{t.description}</p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(t.date).toLocaleDateString()} ·{" "}
                        {Math.abs(t.amount).toLocaleString("en-US", {
                          style: "currency",
                          currency: "USD",
                        })}
                        {t.category && ` · ${t.category}`}
                      </p>
                      {t.anomaly_reason && (
                        <p className="text-xs text-muted-foreground italic">
                          {t.anomaly_reason}
                        </p>
                      )}
                    </div>
                    <Badge variant="destructive" className="shrink-0 text-xs">
                      Score: {t.anomaly_score?.toFixed(2) ?? "—"}
                    </Badge>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Suggestions tab */}
        <TabsContent value="suggestions">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">Savings Suggestions</CardTitle>
              <Button
                size="sm"
                variant="outline"
                onClick={() => generate.mutate()}
                disabled={generate.isPending}
              >
                {generate.isPending ? "Generating…" : "Refresh Suggestions"}
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {suggestions.isError ? (
                <p className="text-sm text-muted-foreground">
                  Savings suggestions require a{" "}
                  <span className="font-medium text-primary">Premium</span>{" "}
                  subscription.
                </p>
              ) : suggestions.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : !suggestions.data?.suggestions.length ? (
                <p className="text-sm text-muted-foreground">
                  No suggestions yet. Click &quot;Refresh Suggestions&quot; to generate them.
                </p>
              ) : (
                suggestions.data.suggestions.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-start justify-between rounded-lg border p-3 gap-4"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary" className="text-xs capitalize">
                          {s.suggestion_type.replace(/_/g, " ")}
                        </Badge>
                        {s.category && (
                          <span className="text-xs text-muted-foreground">
                            {s.category}
                          </span>
                        )}
                      </div>
                      <p className="text-sm">{s.description}</p>
                      {s.estimated_savings != null && (
                        <p className="text-xs font-medium text-green-600 dark:text-green-400">
                          Est. savings: $
                          {Number(s.estimated_savings).toLocaleString("en-US", {
                            minimumFractionDigits: 2,
                          })}
                        </p>
                      )}
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 shrink-0"
                      onClick={() => dismiss.mutate(s.id)}
                      title="Dismiss"
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
