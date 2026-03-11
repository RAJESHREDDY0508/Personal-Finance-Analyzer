"use client";

import { useEffect, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  FileText,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Loader2,
  XCircle,
  CheckCircle2,
  AlertCircle,
  ReceiptText,
} from "lucide-react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import api from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────
interface Statement {
  id: string;
  file_name: string;
  file_type: string;
  status: string;
  row_count: number | null;
  error_message: string | null;
  uploaded_at: string;
  processed_at: string | null;
}

interface Transaction {
  id: string;
  date: string;
  description: string;
  amount: string;
  category: string | null;
  subcategory: string | null;
  is_income: boolean;
  is_anomaly: boolean;
  anomaly_reason: string | null;
  is_duplicate: boolean;
}

interface TransactionPage {
  items: Transaction[];
  total: number;
}

// ── Helpers ────────────────────────────────────────────────────
const COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f97316",
  "#eab308", "#22c55e", "#14b8a6", "#0ea5e9", "#64748b",
];

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

const STATUS_BADGE: Record<string, "secondary" | "outline" | "default" | "destructive"> = {
  pending: "secondary",
  processing: "outline",
  completed: "default",
  failed: "destructive",
};

// ── Page ───────────────────────────────────────────────────────
export default function StatementAnalysisPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  // Poll statement until it reaches a terminal state
  const { data: statement, isLoading: stmtLoading } = useQuery<Statement>({
    queryKey: ["statement", id],
    queryFn: () => api.get(`/statements/${id}`).then((r) => r.data),
    refetchInterval: (query) => {
      const s = query.state.data;
      if (!s) return 3000;
      return s.status === "pending" || s.status === "processing" ? 3000 : false;
    },
    enabled: !!id,
  });

  // Fetch transactions once the statement is completed
  const { data: txnData } = useQuery<TransactionPage>({
    queryKey: ["statement-transactions", id],
    queryFn: () =>
      api
        .get(`/transactions?statement_id=${id}&limit=200`)
        .then((r) => ({ items: r.data.items ?? r.data, total: r.data.total ?? 0 })),
    enabled: statement?.status === "completed",
    staleTime: 30_000,
  });

  const transactions = txnData?.items ?? [];

  // ── Derived stats ──────────────────────────────────────────
  const stats = useMemo(() => {
    const income = transactions
      .filter((t) => t.is_income)
      .reduce((s, t) => s + Math.abs(parseFloat(t.amount)), 0);
    const expenses = transactions
      .filter((t) => !t.is_income)
      .reduce((s, t) => s + Math.abs(parseFloat(t.amount)), 0);
    const balance = income - expenses;
    const anomalies = transactions.filter((t) => t.is_anomaly).length;
    return { income, expenses, balance, anomalies };
  }, [transactions]);

  // Spending by category (expenses only)
  const categoryData = useMemo(() => {
    const map: Record<string, number> = {};
    transactions
      .filter((t) => !t.is_income)
      .forEach((t) => {
        const cat = t.category ?? "Other";
        map[cat] = (map[cat] ?? 0) + Math.abs(parseFloat(t.amount));
      });
    return Object.entries(map)
      .sort(([, a], [, b]) => b - a)
      .map(([name, value]) => ({ name, value }));
  }, [transactions]);

  // ── Render helpers ─────────────────────────────────────────
  const isProcessing =
    stmtLoading || statement?.status === "pending" || statement?.status === "processing";

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Back button */}
      <Button variant="ghost" size="sm" onClick={() => router.push("/upload")}>
        <ArrowLeft className="h-4 w-4 mr-2" />
        Back to Uploads
      </Button>

      {/* Statement header */}
      {statement && (
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <FileText className="h-6 w-6 text-muted-foreground shrink-0" />
            <div>
              <h1 className="text-xl font-bold tracking-tight">{statement.file_name}</h1>
              <p className="text-sm text-muted-foreground">
                Uploaded {new Date(statement.uploaded_at).toLocaleDateString()}
                {statement.row_count != null && ` · ${statement.row_count} transactions`}
              </p>
            </div>
          </div>
          <Badge variant={STATUS_BADGE[statement.status] ?? "secondary"}>
            {statement.status === "processing" && (
              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            )}
            {statement.status === "completed" && (
              <CheckCircle2 className="h-3 w-3 mr-1" />
            )}
            {statement.status === "failed" && <XCircle className="h-3 w-3 mr-1" />}
            {statement.status.charAt(0).toUpperCase() + statement.status.slice(1)}
          </Badge>
        </div>
      )}

      {/* ── Processing state ─────────────────────────────── */}
      {isProcessing && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 gap-4">
            <div className="relative">
              <div className="h-16 w-16 rounded-full border-4 border-primary/20" />
              <Loader2 className="h-16 w-16 animate-spin text-primary absolute inset-0" />
            </div>
            <div className="text-center">
              <p className="font-semibold text-lg">
                {!statement || statement.status === "pending"
                  ? "Queued for processing…"
                  : "Analyzing your statement…"}
              </p>
              <p className="text-sm text-muted-foreground mt-1">
                {statement?.status === "processing"
                  ? "AI is categorizing your transactions. This usually takes 15–30 seconds."
                  : "Your file is in the queue. Starting shortly…"}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Failed state ─────────────────────────────────── */}
      {statement?.status === "failed" && (
        <Card className="border-destructive">
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <XCircle className="h-12 w-12 text-destructive" />
            <p className="font-semibold text-destructive">Processing failed</p>
            {statement.error_message && (
              <p className="text-sm text-muted-foreground text-center max-w-md">
                {statement.error_message}
              </p>
            )}
            <Button
              variant="outline"
              onClick={() =>
                api.post(`/statements/${id}/reprocess`).then(() => router.refresh())
              }
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ── Analysis results ──────────────────────────────── */}
      {statement?.status === "completed" && transactions.length > 0 && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
                  <TrendingUp className="h-4 w-4 text-green-500" />
                  Total Income
                </div>
                <p className="text-2xl font-bold text-green-600">{fmt(stats.income)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
                  <TrendingDown className="h-4 w-4 text-red-500" />
                  Total Expenses
                </div>
                <p className="text-2xl font-bold text-red-600">{fmt(stats.expenses)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
                  <DollarSign className="h-4 w-4 text-primary" />
                  Net Balance
                </div>
                <p
                  className={`text-2xl font-bold ${
                    stats.balance >= 0 ? "text-green-600" : "text-red-600"
                  }`}
                >
                  {fmt(stats.balance)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
                  <AlertCircle className="h-4 w-4 text-amber-500" />
                  Anomalies
                </div>
                <p className="text-2xl font-bold">{stats.anomalies}</p>
              </CardContent>
            </Card>
          </div>

          {/* Charts */}
          {categoryData.length > 0 && (
            <div className="grid md:grid-cols-2 gap-6">
              {/* Pie chart */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Spending by Category</CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={260}>
                    <PieChart>
                      <Pie
                        data={categoryData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={90}
                        label={({ name, percent }) =>
                          `${name} ${(percent * 100).toFixed(0)}%`
                        }
                        labelLine={false}
                      >
                        {categoryData.map((_, i) => (
                          <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v: number) => fmt(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Bar chart */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Top Categories</CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart
                      data={categoryData.slice(0, 8)}
                      layout="vertical"
                      margin={{ left: 16, right: 24, top: 4, bottom: 4 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" tickFormatter={(v) => `$${v}`} fontSize={11} />
                      <YAxis type="category" dataKey="name" width={110} fontSize={11} />
                      <Tooltip formatter={(v: number) => fmt(v)} />
                      <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                        {categoryData.slice(0, 8).map((_, i) => (
                          <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Transactions table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <ReceiptText className="h-4 w-4" />
                Transactions ({transactions.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead>Description</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead className="text-right">Amount</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {transactions.map((t) => (
                      <TableRow key={t.id}>
                        <TableCell className="whitespace-nowrap text-sm">
                          {new Date(t.date).toLocaleDateString()}
                        </TableCell>
                        <TableCell className="max-w-[260px] truncate text-sm">
                          {t.description}
                        </TableCell>
                        <TableCell>
                          {t.category ? (
                            <Badge variant="outline" className="text-xs">
                              {t.category}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono text-sm font-medium ${
                            t.is_income ? "text-green-600" : "text-foreground"
                          }`}
                        >
                          {t.is_income ? "+" : ""}
                          {fmt(Math.abs(parseFloat(t.amount)))}
                        </TableCell>
                        <TableCell className="text-right">
                          {t.is_anomaly && (
                            <AlertCircle
                              className="h-4 w-4 text-amber-500 inline-block"
                              title={t.anomaly_reason ?? "Anomaly detected"}
                            />
                          )}
                          {t.is_duplicate && (
                            <span
                              className="text-xs text-muted-foreground ml-1"
                              title="Possible duplicate"
                            >
                              dup
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* Completed but no transactions parsed */}
      {statement?.status === "completed" && transactions.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center py-12 gap-3">
            <FileText className="h-10 w-10 text-muted-foreground" />
            <p className="text-muted-foreground">No transactions found in this file.</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
