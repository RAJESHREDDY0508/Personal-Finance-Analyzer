"use client";

import { useQuery } from "@tanstack/react-query";
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  AlertTriangle,
  Activity,
  Heart,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import StatCard from "@/components/stat-card";
import SpendingPieChart from "@/components/charts/spending-pie";
import TrendChart from "@/components/charts/trend-chart";
import SavingsChart from "@/components/charts/savings-chart";
import { StatCardSkeleton, ChartSkeleton } from "@/components/loading-skeleton";
import api from "@/lib/api";

const fmt = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
  });

const today = new Date();
const qp = `year=${today.getFullYear()}&month=${today.getMonth() + 1}`;

function healthColor(score: number) {
  if (score >= 70) return "text-green-600 dark:text-green-400";
  if (score >= 40) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

function healthLabel(score: number) {
  if (score >= 70) return "Great";
  if (score >= 40) return "Fair";
  return "Needs attention";
}

export default function DashboardPage() {
  const overview = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: () =>
      api.get(`/dashboard/overview?${qp}`).then((r) => r.data),
  });

  const category = useQuery({
    queryKey: ["dashboard", "category"],
    queryFn: () =>
      api.get(`/dashboard/spending-by-category?${qp}`).then((r) => r.data),
  });

  const trend = useQuery({
    queryKey: ["dashboard", "trend"],
    queryFn: () =>
      api.get("/dashboard/spending-trend?months=6").then((r) => r.data),
  });

  const savings = useQuery({
    queryKey: ["dashboard", "savings"],
    queryFn: () =>
      api.get("/dashboard/savings-rate?months=6").then((r) => r.data),
  });

  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => api.get("/users/me").then((r) => r.data),
  });

  const ov = overview.data;
  const healthScore: number = profile.data?.health_score ?? 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {overview.isLoading ? (
          Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)
        ) : (
          <>
            <StatCard
              title="Income"
              value={fmt(ov?.income ?? 0)}
              icon={TrendingUp}
              trend="up"
              sub="This month"
            />
            <StatCard
              title="Expenses"
              value={fmt(ov?.expenses ?? 0)}
              icon={TrendingDown}
              trend="down"
              sub="This month"
            />
            <StatCard
              title="Net Savings"
              value={fmt(ov?.net ?? 0)}
              icon={DollarSign}
              trend={(ov?.net ?? 0) >= 0 ? "up" : "down"}
              sub={`${(((ov?.savings_rate ?? 0) as number) * 100).toFixed(1)}% rate`}
            />
            <StatCard
              title="Anomalies"
              value={ov?.anomaly_count ?? 0}
              icon={AlertTriangle}
              trend={(ov?.anomaly_count ?? 0) > 0 ? "down" : "neutral"}
              sub="Flagged this month"
            />
          </>
        )}
      </div>

      {/* Health score banner */}
      {!profile.isLoading && (
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted shrink-0">
                <Heart className={`h-6 w-6 ${healthColor(healthScore)}`} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">Financial Health Score</p>
                <p className="text-xs text-muted-foreground">
                  {healthLabel(healthScore)} — based on your spending and savings patterns
                </p>
              </div>
              <div className="text-right shrink-0">
                <span
                  className={`text-3xl font-bold tabular-nums ${healthColor(healthScore)}`}
                >
                  {healthScore}
                </span>
                <span className="text-muted-foreground text-sm">/100</span>
              </div>
            </div>
            {/* Progress bar */}
            <div className="mt-3 h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  healthScore >= 70
                    ? "bg-green-500"
                    : healthScore >= 40
                    ? "bg-yellow-500"
                    : "bg-red-500"
                }`}
                style={{ width: `${Math.min(100, Math.max(0, healthScore))}%` }}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Spending by Category</CardTitle>
          </CardHeader>
          <CardContent>
            {category.isLoading ? (
              <ChartSkeleton />
            ) : (
              <SpendingPieChart data={category.data ?? []} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Monthly Spending Trend</CardTitle>
          </CardHeader>
          <CardContent>
            {trend.isLoading ? (
              <ChartSkeleton />
            ) : (
              <TrendChart data={trend.data ?? []} />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Savings bar chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Income vs Expenses — last 6 months
          </CardTitle>
        </CardHeader>
        <CardContent>
          {savings.isLoading ? (
            <ChartSkeleton />
          ) : (
            <SavingsChart data={savings.data ?? []} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
