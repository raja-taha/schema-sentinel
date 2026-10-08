const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "change-me-to-a-strong-secret";

export type SampleMigration = {
  id: string;
  filename: string;
  title: string;
  source_type: string;
  preview: string;
  bytes: number;
};

export type TableStats = {
  source: string;
  url_host: string | null;
  rows: Record<string, number>;
  details: Array<{
    schema_name: string;
    table_name: string;
    row_estimate: number;
    size_bytes: number;
    index_count: number;
  }>;
  error: string | null;
};

export type AnalysisSummary = {
  id: string;
  title: string;
  source_type: string;
  scenario_id: string | null;
  status: string;
  overall_risk: string | null;
  overall_score: number | null;
  created_at: string | null;
  completed_at: string | null;
};

export type RiskFinding = {
  rule_id: string;
  title: string;
  severity: string;
  category: string;
  score: number;
  table?: string | null;
  column?: string | null;
  message: string;
  reversible: boolean;
  evidence?: Record<string, unknown>;
};

export type AnalysisDetail = AnalysisSummary & {
  migration_sql: string;
  migration_filename: string | null;
  repo_path: string | null;
  operations: Array<Record<string, unknown>> | null;
  risk_findings: RiskFinding[] | null;
  dependency_graph: {
    nodes?: Array<Record<string, unknown>>;
    edges?: Array<Record<string, unknown>>;
    blast_radius?: Record<string, unknown>;
    stats?: Record<string, number>;
    stats_source?: string;
    stats_host?: string;
  } | null;
  code_references: Array<{
    path: string;
    line: number;
    snippet: string;
    table?: string;
    column?: string;
    symbol?: string;
    endpoint_hint?: string | null;
  }> | null;
  rollout_plan: Array<{
    phase: string;
    title: string;
    description: string;
    actions: string[];
  }> | null;
  rollback_sql: string | null;
  llm_explanation: string | null;
  markdown_report: string | null;
  agent_trace: Array<Record<string, unknown>> | null;
  error_message: string | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "X-API-Key": API_KEY,
    ...(init?.headers as Record<string, string> | undefined),
  };
  // Don't force JSON content-type on FormData uploads
  if (!(init?.body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () =>
    request<{ status: string; use_openai: boolean; agent_mode: string }>("/api/v1/health"),
  stats: () => request<TableStats>("/api/v1/stats"),
  samples: () => request<SampleMigration[]>("/api/v1/samples"),
  sample: (filename: string) =>
    request<{ filename: string; migration_sql: string; source_type: string; title: string }>(
      `/api/v1/samples/${encodeURIComponent(filename)}`
    ),
  analyses: () => request<AnalysisSummary[]>("/api/v1/analyses"),
  analysis: (id: string) => request<AnalysisDetail>(`/api/v1/analyses/${id}`),
  createAnalysis: (body: {
    scenario_id?: string;
    sample_filename?: string;
    migration_sql?: string;
    migration_filename?: string;
    source_type?: string;
    title?: string;
    auto_analyze?: boolean;
  }) =>
    request<AnalysisDetail>("/api/v1/analyses", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  upload: async (file: File, title?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    form.append("auto_analyze", "true");
    return request<AnalysisDetail>("/api/v1/analyses/upload", {
      method: "POST",
      body: form,
    });
  },
  rerun: (id: string) =>
    request<AnalysisDetail>(`/api/v1/analyses/${id}/rerun`, { method: "POST" }),
};
