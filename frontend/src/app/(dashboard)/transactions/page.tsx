"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
import { TableRowSkeleton } from "@/components/loading-skeleton";
import api from "@/lib/api";

const CATEGORIES = [
  "All",
  "Food & Dining",
  "Groceries",
  "Shopping",
  "Transportation",
  "Entertainment",
  "Health & Medical",
  "Housing",
  "Utilities",
  "Travel",
  "Education",
  "Personal Care",
  "Gifts & Donations",
  "Business Services",
  "Income",
  "Transfers",
  "Other",
];

interface Transaction {
  id: string;
  date: string;
  description: string;
  amount: number;
  category: string | null;
  is_income: boolean;
  is_anomaly: boolean;
  categorization_source: string | null;
}

export default function TransactionsPage() {
  const qc = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [search, setSearch] = useState("");

  const transactions = useQuery<Transaction[]>({
    queryKey: ["transactions", categoryFilter],
    queryFn: () => {
      const params = new URLSearchParams({ limit: "100" });
      if (categoryFilter !== "All") params.set("category", categoryFilter);
      return api.get(`/transactions/?${params}`).then((r) => r.data);
    },
  });

  const updateCategory = useMutation({
    mutationFn: ({ id, category }: { id: string; category: string }) =>
      api.patch(`/transactions/${id}/category`, { category }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      toast.success("Category updated");
    },
    onError: () => toast.error("Failed to update category"),
  });

  const filtered = (transactions.data ?? []).filter((t) =>
    t.description.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Transactions</h1>

      {/* Filters */}
      <div className="flex gap-3">
        <Input
          placeholder="Search description…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <Select value={categoryFilter} onValueChange={(v) => { if (v) setCategoryFilter(v); }}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Category" />
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

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Flags</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {transactions.isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <TableRowSkeleton key={i} cols={5} />
                ))
              ) : !filtered.length ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    No transactions found
                  </TableCell>
                </TableRow>
              ) : (
                filtered.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="text-sm whitespace-nowrap">
                      {new Date(t.date).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-sm max-w-xs truncate">
                      {t.description}
                    </TableCell>
                    <TableCell
                      className={`text-right text-sm font-medium ${
                        t.is_income ? "text-green-600 dark:text-green-400" : ""
                      }`}
                    >
                      {t.is_income ? "+" : ""}
                      {Math.abs(t.amount).toLocaleString("en-US", {
                        style: "currency",
                        currency: "USD",
                      })}
                    </TableCell>
                    <TableCell>
                      <Select
                        value={t.category ?? "Other"}
                        onValueChange={(val) => {
                          if (val) updateCategory.mutate({ id: t.id, category: val });
                        }}
                      >
                        <SelectTrigger className="h-7 text-xs w-40">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {CATEGORIES.filter((c) => c !== "All").map((c) => (
                            <SelectItem key={c} value={c} className="text-xs">
                              {c}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      {t.is_anomaly && (
                        <Badge variant="destructive" className="text-xs gap-1">
                          <AlertTriangle className="h-3 w-3" />
                          Anomaly
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
