"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { GraphMini } from "@/components/GraphMini";
import { RiskBadge } from "@/components/RiskBadge";
import { api, AnalysisDetail } from "@/lib/api";

export default function AnalysisPage() {
  const params = useParams();
  const id = String(params.id);
  const [data, setData] = useState<AnalysisDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function load() {
    return api.analysis(id).then(setData);
  }

  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
  }, [id]);

  function onRerun() {
    startTransition(async () => {
      try {
        const next = await api.rerun(id);
        setData(next);
      } catch (e) {
        setError(String((e as Error).message || e));
      }
    });
  }

  if (error) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-16">
        <p className="font-mono text-sm text-danger">{error}</p>
        <Link href="/" className="mt-4 inline-block text-teal underline">
          Back
        </Link>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-16">
        <p className="animate-pulse font-mono text-sm text-slateish/60">Loading analysis…</p>
      </main>
    );
  }

  const findings = data.risk_findings || [];
  const ops = data.operations || [];
  const refs = data.code_references || [];
  const plan = data.rollout_plan || [];

  return (
    <main className="mx-auto max-w-6xl px-6 pb-20 pt-8">
      <div className="animate-rise mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/" className="font-mono text-[11px] uppercase tracking-wider text-teal">
            ← SchemaSentinel
          </Link>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight md:text-4xl">{data.title}</h1>
          <p className="mt-2 font-mono text-xs text-slateish/60">
            {data.source_type}
            {data.migration_filename ? ` · ${data.migration_filename}` : ""} · score{" "}
            {data.overall_score?.toFixed(2) ?? "—"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <RiskBadge value={data.overall_risk || data.status} />
          <button
            type="button"
            onClick={onRerun}
            disabled={pending}
            className="rounded-xl bg-ink px-4 py-2 text-sm text-foam disabled:opacity-50"
          >
            {pending ? "Re-running…" : "Re-run"}
          </button>
        </div>
      </div>

      <section className="animate-rise grid gap-6 md:grid-cols-3" style={{ animationDelay: "60ms" }}>
        <Stat label="Operations" value={String(ops.length)} />
        <Stat label="Findings" value={String(findings.length)} />
        <Stat label="Code refs" value={String(refs.length)} />
      </section>

      <div className="mt-8 grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="animate-rise space-y-6" style={{ animationDelay: "100ms" }}>
          <Panel title="Deterministic findings">
            <ul className="space-y-3">
              {findings.map((f) => (
                <li
                  key={`${f.rule_id}-${f.table}-${f.column}-${f.title}`}
                  className="rounded-xl border border-ink/8 bg-foam/40 px-4 py-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium">{f.title}</p>
                    <RiskBadge value={f.severity} />
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-slateish/55">
                    {f.rule_id} · {f.category} · score {f.score}
                    {!f.reversible ? " · irreversible" : ""}
                  </p>
                  <p className="mt-2 text-sm text-slateish/80">{f.message}</p>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="LLM explanation">
            <pre className="whitespace-pre-wrap font-display text-sm leading-relaxed text-slateish/85">
              {data.llm_explanation || "No explanation."}
            </pre>
          </Panel>

          <Panel title="Rollback SQL sketch">
            <pre className="overflow-x-auto rounded-lg bg-ink px-4 py-3 font-mono text-[11px] leading-relaxed text-foam">
              {data.rollback_sql || "-- none"}
            </pre>
          </Panel>
        </section>

        <section className="animate-rise space-y-6" style={{ animationDelay: "140ms" }}>
          <Panel title="Dependency graph">
            <GraphMini
              nodes={(data.dependency_graph?.nodes as never) || []}
              edges={(data.dependency_graph?.edges as never) || []}
            />
            <p className="mt-2 font-mono text-[11px] text-slateish/50">
              {data.dependency_graph?.stats?.node_count ?? 0} nodes ·{" "}
              {data.dependency_graph?.stats?.edge_count ?? 0} edges
            </p>
          </Panel>

          <Panel title="Application references">
            {refs.length === 0 ? (
              <p className="text-sm text-slateish/60">No code references found.</p>
            ) : (
              <ul className="space-y-2">
                {refs.slice(0, 12).map((r, i) => (
                  <li key={`${r.path}-${r.line}-${i}`} className="rounded-lg bg-foam/50 px-3 py-2">
                    <p className="font-mono text-[11px] text-teal">
                      {r.path}:{r.line}
                      {r.endpoint_hint ? ` · ${r.endpoint_hint}` : ""}
                    </p>
                    <p className="mt-1 truncate font-mono text-[11px] text-slateish/70">
                      {r.snippet}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Phased rollout">
            <ol className="space-y-4">
              {plan.map((step) => (
                <li key={step.phase}>
                  <p className="font-mono text-[11px] uppercase tracking-wider text-teal">
                    {step.phase}
                  </p>
                  <p className="mt-1 text-sm font-medium">{step.title}</p>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slateish/75">
                    {(step.actions || []).slice(0, 4).map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          </Panel>

          <Panel title="Agent trace">
            <ul className="space-y-1 font-mono text-[11px] text-slateish/65">
              {(data.agent_trace || []).map((t, i) => (
                <li key={i}>
                  {String(t.step)} → {String(t.detail)}
                </li>
              ))}
            </ul>
          </Panel>
        </section>
      </div>

      <section className="animate-rise mt-8" style={{ animationDelay: "180ms" }}>
        <Panel title="Migration source">
          <pre className="overflow-x-auto rounded-lg bg-ink/95 px-4 py-3 font-mono text-[11px] text-foam">
            {data.migration_sql}
          </pre>
        </Panel>
      </section>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-ink/10 bg-white/70 px-5 py-4 shadow-panel">
      <p className="font-mono text-[11px] uppercase tracking-wider text-slateish/55">{label}</p>
      <p className="mt-1 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-ink/10 bg-white/75 p-5 shadow-panel backdrop-blur">
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="mt-4">{children}</div>
    </div>
  );
}
