"use client";

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

const COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f97316",
  "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#a78bfa",
];

interface SpendingItem {
  category: string;
  total: number;
  percentage: number;
}

export default function SpendingPieChart({ data }: { data: SpendingItem[] }) {
  if (!data.length) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        No spending data for this period
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <PieChart>
        <Pie
          data={data}
          dataKey="total"
          nameKey="category"
          cx="50%"
          cy="50%"
          outerRadius={90}
          label={(props: { name?: string; percent?: number }) =>
            `${props.name ?? ""} ${((props.percent ?? 0) * 100).toFixed(0)}%`
          }
          labelLine={false}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          formatter={(v) => {
            const num = typeof v === "number" ? v : 0;
            return `$${num.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
          }}
        />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  );
}
