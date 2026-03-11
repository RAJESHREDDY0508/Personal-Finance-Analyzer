"use client";

import { useQuery } from "@tanstack/react-query";
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  AlertTriangle,
  Activity,
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

  const ov = overview.data;

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
