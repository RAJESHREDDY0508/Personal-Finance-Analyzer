"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronLeft, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

const PAGE_SIZE = 25;

interface Transaction {
  id: string;
  date: string;
  description: string;
  amount: string;
  category: string | null;
  is_income: boolean;
  is_anomaly: boolean;
  categorization_source: string | null;
}

interface TransactionsResponse {
  items: Transaction[];
  total: number;
  page: number;
  pages: number;
}

export default function TransactionsPage() {
  const qc = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const transactions = useQuery<TransactionsResponse>({
    queryKey: ["transactions", categoryFilter, page],
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String((page - 1) * PAGE_SIZE),
      });
      if (categoryFilter !== "All") params.set("category", categoryFilter);
      if (search.trim()) params.set("search", search.trim());
      return api.get(`/transactions?${params}`).then((r) => {
        // Handle both paginated {items, total} and plain array responses
        if (Array.isArray(r.data)) {
          return { items: r.data, total: r.data.length, page: 1, pages: 1 };
        }
        return r.data;
      });
    },
  });

  // Reset to page 1 when filters change
  function handleCategoryChange(val: string | null) {
    setCategoryFilter(val ?? "All");
    setPage(1);
  }

  function handleSearchChange(val: string) {
    setSearch(val);
    setPage(1);
  }

  const updateCategory = useMutation({
    mutationFn: ({ id, category }: { id: string; category: string }) =>
      api.patch(`/transactions/${id}/category`, { category }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      toast.success("Category updated");
    },
    onError: () => toast.error("Failed to update category"),
  });

  const items = transactions.data?.items ?? [];
  const totalPages = transactions.data?.pages ?? 1;
  const total = transactions.data?.total ?? 0;

  // Client-side description filter (for the current page)
  const filtered = search.trim()
    ? items.filter((t) =>
        t.description.toLowerCase().includes(search.toLowerCase())
      )
    : items;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Transactions</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <Input
          placeholder="Search description…"
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
          className="max-w-xs"
        />
        <Select
          value={categoryFilter}
          onValueChange={handleCategoryChange}
        >
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
                  <TableCell
                    colSpan={5}
                    className="text-center text-muted-foreground py-8"
                  >
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
                      {Math.abs(parseFloat(t.amount)).toLocaleString("en-US", {
                        style: "currency",
                        currency: "USD",
                      })}
                    </TableCell>
                    <TableCell>
                      <Select
                        value={t.category ?? "Other"}
                        onValueChange={(val: string | null) => {
                          if (val != null)
                            updateCategory.mutate({ id: t.id, category: val });
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

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            {total} transactions &mdash; page {page} of {totalPages}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1 || transactions.isLoading}
            >
              <ChevronLeft className="h-4 w-4" />
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || transactions.isLoading}
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
