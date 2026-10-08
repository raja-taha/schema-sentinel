"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState, useTransition } from "react";
import { RiskBadge } from "@/components/RiskBadge";
import { api, AnalysisSummary, Scenario } from "@/lib/api";

export default function HomePage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [sql, setSql] = useState("");
  const [mode, setMode] = useState<"scenario" | "sql">("scenario");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  async function refresh() {
    const [s, a] = await Promise.all([api.scenarios(), api.analyses()]);
    setScenarios(s);
    setAnalyses(a);
    if (!selected && s[0]) setSelected(s[0].id);
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message || e)));
  }, []);

  function onAnalyze(e: FormEvent) {
    e.preventDefault();
    setError(null);
    startTransition(async () => {
      try {
        const analysis =
          mode === "scenario"
            ? await api.createAnalysis({ scenario_id: selected, auto_analyze: true })
            : await api.createAnalysis({
                migration_sql: sql,
                source_type: "sql",
                title: "Custom migration",
                auto_analyze: true,
              });
        window.location.href = `/analyses/${analysis.id}`;
      } catch (err) {
        setError(String((err as Error).message || err));
      }
    });
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col px-6 pb-16 pt-10">
      <header className="animate-rise mb-14">
        <p className="font-mono text-xs uppercase tracking-[0.28em] text-teal">
          AI + Databases · Static analysis
        </p>
        <h1 className="mt-4 max-w-3xl text-5xl font-semibold tracking-tight text-ink md:text-6xl">
          SchemaSentinel
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-relaxed text-slateish/80">
          Treat schema migrations like software changes — parse DDL, score lock and
          data-loss risk, map blast radius across your codebase, then ship with
          expand/backfill/switch/contract guidance.
        </p>
        <div className="mt-6 h-1 w-44 origin-left animate-pulsebar rounded-full bg-gradient-to-r from-teal via-ice to-transparent" />
      </header>

      <section
        className="animate-rise grid gap-8 md:grid-cols-[1.15fr_0.85fr]"
        style={{ animationDelay: "80ms" }}
      >
        <form
          onSubmit={onAnalyze}
          className="rounded-2xl border border-ink/10 bg-white/75 p-6 shadow-panel backdrop-blur"
        >
          <div className="flex gap-2 font-mono text-[11px] uppercase tracking-wider">
            <button
              type="button"
              onClick={() => setMode("scenario")}
              className={`rounded-md px-3 py-1.5 ring-1 ${
                mode === "scenario"
                  ? "bg-ink text-foam ring-ink"
                  : "bg-foam text-slateish ring-ink/10"
              }`}
            >
              Sample scenario
            </button>
            <button
              type="button"
              onClick={() => setMode("sql")}
              className={`rounded-md px-3 py-1.5 ring-1 ${
                mode === "sql"
                  ? "bg-ink text-foam ring-ink"
                  : "bg-foam text-slateish ring-ink/10"
              }`}
            >
              Paste SQL
            </button>
          </div>

          <h2 className="mt-5 text-xl font-semibold">Analyze a migration</h2>
          <p className="mt-2 text-sm text-slateish/70">
            Deterministic rules run first. The LLM only explains blast radius — it
            never overrides severity.
          </p>

          {mode === "scenario" ? (
            <>
              <label className="mt-6 block font-mono text-[11px] uppercase tracking-wider text-slateish/60">
                Scenario
              </label>
              <select
                className="mt-2 w-full rounded-xl border border-ink/15 bg-foam/60 px-3 py-3 text-sm outline-none ring-teal focus:ring-2"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {scenarios.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title} · expected {s.expected_risk}
                  </option>
                ))}
              </select>
              {selected ? (
                <p className="mt-3 text-sm text-slateish/75">
                  {scenarios.find((s) => s.id === selected)?.description}
                </p>
              ) : null}
            </>
          ) : (
            <>
              <label className="mt-6 block font-mono text-[11px] uppercase tracking-wider text-slateish/60">
                Migration SQL
              </label>
              <textarea
                className="mt-2 h-40 w-full rounded-xl border border-ink/15 bg-foam/60 px-3 py-3 font-mono text-xs outline-none ring-teal focus:ring-2"
                placeholder="ALTER TABLE users ADD COLUMN email varchar(255) NOT NULL;"
                value={sql}
                onChange={(e) => setSql(e.target.value)}
              />
            </>
          )}

          {error ? (
            <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 font-mono text-xs text-danger">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={pending || (mode === "scenario" ? !selected : !sql.trim())}
            className="mt-6 inline-flex items-center justify-center rounded-xl bg-ink px-5 py-3 text-sm font-medium text-foam transition hover:bg-slateish disabled:opacity-50"
          >
            {pending ? "Analyzing…" : "Run risk analysis"}
          </button>
        </form>

        <aside className="rounded-2xl border border-ink/10 bg-white/60 p-6 backdrop-blur">
          <h2 className="text-lg font-semibold">Recent analyses</h2>
          <p className="mt-1 text-sm text-slateish/65">Latest runs from this environment.</p>
          <ul className="mt-5 space-y-3">
            {analyses.length === 0 ? (
              <li className="text-sm text-slateish/60">No analyses yet — run a scenario.</li>
            ) : (
              analyses.slice(0, 6).map((a) => (
                <li key={a.id}>
                  <Link
                    href={`/analyses/${a.id}`}
                    className="flex items-start justify-between gap-3 rounded-xl border border-ink/5 bg-foam/50 px-3 py-3 transition hover:border-teal/30"
                  >
                    <div>
                      <p className="text-sm font-medium">{a.title}</p>
                      <p className="mt-1 font-mono text-[11px] text-slateish/55">
                        {a.source_type} · {a.status}
                      </p>
                    </div>
                    <RiskBadge value={a.overall_risk || a.status} />
                  </Link>
                </li>
              ))
            )}
          </ul>
        </aside>
      </section>
    </main>
  );
}
