import { cn } from "@/lib/utils";

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
    />
  );
}

export function StatCardSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-5 space-y-3">
      <Skeleton className="h-4 w-28" />
      <Skeleton className="h-8 w-20" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
}

export function ChartSkeleton({ height = "h-64" }: { height?: string }) {
  return <Skeleton className={cn("w-full rounded-xl", height)} />;
}

export function TableRowSkeleton({ cols = 5 }: { cols?: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <Skeleton className="h-4 w-full" />
        </td>
      ))}
    </tr>
  );
}

export default Skeleton;
