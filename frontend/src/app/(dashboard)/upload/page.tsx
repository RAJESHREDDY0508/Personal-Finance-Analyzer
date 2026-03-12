"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import api from "@/lib/api";
import axios from "axios";
import { cn } from "@/lib/utils";

interface Statement {
  id: string;
  file_name: string;
  status: string;
  row_count: number | null;
  uploaded_at: string;
}

const BADGE: Record<string, "secondary" | "outline" | "default" | "destructive"> = {
  pending: "secondary",
  processing: "outline",
  completed: "default",
  failed: "destructive",
};

export default function UploadPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const [uploading, setUploading] = useState(false);

  const statements = useQuery<Statement[]>({
    queryKey: ["statements"],
    queryFn: () =>
      api.get("/statements").then((r) => {
        const raw = r.data;
        return Array.isArray(raw?.statements) ? raw.statements : Array.isArray(raw) ? raw : [];
      }),
    refetchInterval: (query) => {
      const data = Array.isArray(query.state.data) ? (query.state.data as Statement[]) : [];
      return data.some((s) => s.status === "pending" || s.status === "processing")
        ? 3000
        : false;
    },
  });

  const upload = useCallback(
    async (file: File) => {
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (!["csv", "pdf"].includes(ext ?? "")) {
        toast.error("Only CSV and PDF files are accepted");
        return;
      }
      setUploading(true);
      try {
        const { data } = await api.post("/statements/upload", {
          file_name: file.name,
          file_type: ext,
        });
        const form = new FormData();
        Object.entries(data.upload_fields as Record<string, string>).forEach(
          ([k, v]) => form.append(k, v)
        );
        form.append("file", file);
        // Upload directly to S3
        await axios.post(data.upload_url, form);
        // Only AFTER S3 confirms → tell backend to enqueue SQS (no NoSuchKey race)
        await api.post(`/statements/${data.statement_id}/confirm`);
        toast.success("File uploaded — opening analysis…");
        qc.invalidateQueries({ queryKey: ["statements"] });
        setUploading(false); // reset before navigation so back-button works
        router.push(`/analysis?id=${data.statement_id}`);
      } catch {
        toast.error("Upload failed — please try again");
        setUploading(false);
      }
    },
    [qc, router]
  );

  const onDrop = useCallback(
    (accepted: File[]) => accepted.forEach(upload),
    [upload]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"], "application/pdf": [".pdf"] },
    multiple: true,
    disabled: uploading,
  });

  const reprocess = useMutation({
    mutationFn: (id: string) =>
      api.post(`/statements/${id}/reprocess`).then((r) => r.data),
    onSuccess: (_data, id) => {
      toast.success("Reprocessing started");
      qc.invalidateQueries({ queryKey: ["statements"] });
      router.push(`/analysis?id=${id}`);
    },
  });

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-2xl font-bold tracking-tight">Upload Statement</h1>

      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={cn(
          "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-12 cursor-pointer transition-colors",
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/50 hover:bg-muted/30",
          uploading && "opacity-50 cursor-not-allowed"
        )}
      >
        <input {...getInputProps()} />
        {uploading ? (
          <Loader2 className="h-10 w-10 animate-spin text-primary" />
        ) : (
          <Upload className="h-10 w-10 text-muted-foreground" />
        )}
        <div className="text-center">
          <p className="font-medium">
            {isDragActive ? "Drop files here" : "Drag & drop or click to upload"}
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            Supports CSV and PDF bank statements
          </p>
        </div>
      </div>

      {/* History */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Upload History</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {statements.isLoading ? (
            <p className="p-4 text-sm text-muted-foreground">Loading…</p>
          ) : !statements.data?.length ? (
            <p className="p-4 text-sm text-muted-foreground">
              No statements uploaded yet.
            </p>
          ) : (
            <ul className="divide-y">
              {statements.data.map((s) => (
                <li
                  key={s.id}
                  className={cn(
                    "flex items-center justify-between gap-4 px-4 py-3 transition-colors",
                    s.status === "completed"
                      ? "hover:bg-muted/40 cursor-pointer"
                      : "cursor-default"
                  )}
                  onClick={() => {
                    if (s.status === "completed") router.push(`/analysis?id=${s.id}`);
                  }}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{s.file_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(s.uploaded_at).toLocaleDateString()}
                        {s.row_count != null && ` · ${s.row_count} transactions`}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant={BADGE[s.status] ?? "secondary"}>
                      {s.status === "processing" ? (
                        <span className="flex items-center gap-1">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          Processing
                        </span>
                      ) : s.status === "completed" ? (
                        <span className="flex items-center gap-1">
                          <CheckCircle2 className="h-3 w-3" />
                          Done
                        </span>
                      ) : s.status === "failed" ? (
                        <span className="flex items-center gap-1">
                          <XCircle className="h-3 w-3" />
                          Failed
                        </span>
                      ) : (
                        s.status
                      )}
                    </Badge>
                    {s.status === "failed" && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={(e) => {
                          e.stopPropagation();
                          reprocess.mutate(s.id);
                        }}
                        title="Retry"
                      >
                        <RefreshCw className="h-3 w-3" />
                      </Button>
                    )}
                    {s.status === "completed" && (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
