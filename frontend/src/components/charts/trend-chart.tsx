"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface TrendPoint {
  month: string;
  total: number;
}

export default function TrendChart({ data }: { data: TrendPoint[] }) {
  if (!data.length) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        No trend data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis
          dataKey="month"
          tick={{ fontSize: 11 }}
          tickFormatter={(v) => v.slice(0, 7)}
        />
        <YAxis
          tick={{ fontSize: 11 }}
          tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
        />
        <Tooltip
          formatter={(v) => {
            const num = typeof v === "number" ? v : 0;
            return `$${num.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
          }}
        />
        <Line
          type="monotone"
          dataKey="total"
          stroke="#6366f1"
          strokeWidth={2}
          dot={{ r: 3 }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
