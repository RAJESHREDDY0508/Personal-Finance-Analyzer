"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PiggyBank, TrendingUp, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import api from "@/lib/api";

const CATEGORIES = [
  "Food & Dining", "Groceries", "Shopping", "Transportation",
  "Entertainment", "Health & Medical", "Housing", "Utilities",
  "Travel", "Education", "Personal Care", "Gifts & Donations",
  "Business Services", "Other",
];

const fmt = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

interface BudgetItem {
  id: string;
  category: string;
  monthly_limit: number | null;
  predicted_spend: number | null;
}

interface Prediction {
  category: string;
  month: string;
  predicted_spend: number;
  ml_confidence: number;
  prediction_method: string;
}

interface VsActualItem {
  category: string;
  monthly_limit: number | null;
  predicted_spend: number | null;
  actual_spend: number;
  variance: number;
  variance_pct: number;
}

export default function BudgetPage() {
  const qc = useQueryClient();
  const today = new Date();
  const [category, setCategory] = useState("Groceries");
  const [limit, setLimit] = useState("");

  const budgets = useQuery<BudgetItem[]>({
    queryKey: ["budgets"],
    queryFn: () => api.get("/budgets").then((r) => r.data),
  });

  const predictions = useQuery<{ predictions: Prediction[]; count: number }>({
    queryKey: ["budget-predictions"],
    queryFn: () => api.get("/budgets/predictions").then((r) => r.data),
  });

  const vsActual = useQuery<{ month: string; items: VsActualItem[] }>({
    queryKey: ["budget-vs-actual"],
    queryFn: () => api.get("/budgets/vs-actual").then((r) => r.data),
  });

  const setBudget = useMutation({
    mutationFn: () =>
      api.post("/budgets", {
        category,
        month: `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-01`,
        monthly_limit: parseFloat(limit),
      }).then((r) => r.data),
    onSuccess: () => {
      toast.success(`Budget set for ${category}`);
      setLimit("");
      qc.invalidateQueries({ queryKey: ["budgets"] });
      qc.invalidateQueries({ queryKey: ["budget-vs-actual"] });
    },
    onError: () => toast.error("Failed to set budget"),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Budget & Predictions</h1>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="predictions" className="gap-2">
            <TrendingUp className="h-4 w-4" />
            ML Predictions
          </TabsTrigger>
          <TabsTrigger value="set">Set Budget</TabsTrigger>
        </TabsList>

        {/* vs-actual overview */}
        <TabsContent value="overview">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <PiggyBank className="h-4 w-4" />
                Budget vs Actual — {today.toLocaleString("default", { month: "long", year: "numeric" })}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {vsActual.isLoading ? (
                <p className="p-4 text-sm text-muted-foreground">Loading…</p>
              ) : !vsActual.data?.items.length ? (
                <p className="p-4 text-sm text-muted-foreground">
                  No budget data yet. Set budgets and upload statements to see comparisons.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Category</TableHead>
                      <TableHead className="text-right">Budget Limit</TableHead>
                      <TableHead className="text-right">Predicted</TableHead>
                      <TableHead className="text-right">Actual</TableHead>
                      <TableHead className="text-right">Variance</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {vsActual.data.items.map((item) => (
                      <TableRow key={item.category}>
                        <TableCell className="font-medium">{item.category}</TableCell>
                        <TableCell className="text-right text-sm">
                          {item.monthly_limit != null ? fmt(item.monthly_limit) : "—"}
                        </TableCell>
                        <TableCell className="text-right text-sm">
                          {item.predicted_spend != null ? fmt(item.predicted_spend) : "—"}
                        </TableCell>
                        <TableCell className="text-right text-sm">
                          {fmt(item.actual_spend)}
                        </TableCell>
                        <TableCell className="text-right">
                          <span
                            className={
                              item.variance > 0
                                ? "text-destructive"
                                : "text-green-600 dark:text-green-400"
                            }
                          >
                            {item.variance > 0 ? "+" : ""}
                            {fmt(item.variance)}{" "}
                            <span className="text-xs opacity-70">
                              ({item.variance_pct.toFixed(1)}%)
                            </span>
                          </span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ML predictions tab */}
        <TabsContent value="predictions">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Next Month Spending Predictions
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {predictions.isLoading ? (
                <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Running ML model…
                </div>
              ) : !predictions.data?.predictions.length ? (
                <p className="p-4 text-sm text-muted-foreground">
                  Upload at least one statement to generate predictions.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Category</TableHead>
                      <TableHead className="text-right">Predicted</TableHead>
                      <TableHead>Method</TableHead>
                      <TableHead>Confidence</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {predictions.data.predictions.map((p) => (
                      <TableRow key={p.category}>
                        <TableCell className="font-medium">{p.category}</TableCell>
                        <TableCell className="text-right">{fmt(p.predicted_spend)}</TableCell>
                        <TableCell>
                          <Badge variant="secondary" className="text-xs">
                            {p.prediction_method === "linear_regression"
                              ? "Linear Regression"
                              : "Moving Average"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <div className="w-20 h-2 rounded-full bg-muted overflow-hidden">
                              <div
                                className="h-full bg-primary rounded-full"
                                style={{ width: `${(p.ml_confidence * 100).toFixed(0)}%` }}
                              />
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {(p.ml_confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Set budget tab */}
        <TabsContent value="set">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Set Monthly Budget Limit</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 max-w-sm">
              <div className="space-y-1">
                <Label>Category</Label>
                <Select value={category} onValueChange={(v) => { if (v) setCategory(v); }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Monthly Limit ($)</Label>
                <Input
                  type="number"
                  min="0"
                  step="10"
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                  placeholder="500"
                />
              </div>
              <Button
                onClick={() => setBudget.mutate()}
                disabled={!limit || setBudget.isPending}
                className="w-full"
              >
                {setBudget.isPending ? "Saving…" : "Set Budget"}
              </Button>

              {/* Current budgets */}
              {(budgets.data?.length ?? 0) > 0 && (
                <div className="mt-4 space-y-2">
                  <p className="text-sm font-medium">Current Month Budgets</p>
                  {budgets.data?.map((b) => (
                    <div key={b.id} className="flex justify-between text-sm">
                      <span>{b.category}</span>
                      <span className="font-medium">
                        {b.monthly_limit != null ? fmt(b.monthly_limit) : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
