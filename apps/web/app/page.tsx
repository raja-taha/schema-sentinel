"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState, useTransition } from "react";
import { RiskBadge } from "@/components/RiskBadge";
import {
  api,
  AnalysisSummary,
  SampleMigration,
  TableStats,
} from "@/lib/api";

function formatRows(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatBytes(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)} GB`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} MB`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} KB`;
  return `${n} B`;
}

export default function HomePage() {
  const [samples, setSamples] = useState<SampleMigration[]>([]);
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [stats, setStats] = useState<TableStats | null>(null);
  const [useOpenai, setUseOpenai] = useState(false);
  const [sql, setSql] = useState("");
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState("auto");
  const [filename, setFilename] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  async function refresh() {
    const [s, a, st, h] = await Promise.all([
      api.samples(),
      api.analyses(),
      api.stats(),
      api.health(),
    ]);
    setSamples(s);
    setAnalyses(a);
    setStats(st);
    setUseOpenai(Boolean(h.use_openai));
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message || e)));
  }, []);

  function loadSample(sample: SampleMigration) {
    startTransition(async () => {
      setError(null);
      try {
        const detail = await api.sample(sample.filename);
        setSql(detail.migration_sql);
        setTitle(detail.filename);
        setFilename(detail.filename);
        setSourceType(detail.source_type);
      } catch (err) {
        setError(String((err as Error).message || err));
      }
    });
  }

  function onAnalyze(e: FormEvent) {
    e.preventDefault();
    if (!sql.trim()) return;
    setError(null);
    startTransition(async () => {
      try {
        const analysis = await api.createAnalysis({
          migration_sql: sql,
          migration_filename: filename || undefined,
          source_type: sourceType,
          title: title || filename || "Custom migration",
          auto_analyze: true,
        });
        window.location.href = `/analyses/${analysis.id}`;
      } catch (err) {
        setError(String((err as Error).message || err));
      }
    });
  }

  function onUpload(file: File | null) {
    if (!file) return;
    setError(null);
    startTransition(async () => {
      try {
        const analysis = await api.upload(file);
        window.location.href = `/analyses/${analysis.id}`;
      } catch (err) {
        setError(String((err as Error).message || err));
      }
    });
  }

  const liveTables = (stats?.details || [])
    .filter((d) =>
      ["users", "orders", "payments", "products", "accounts"].includes(d.table_name)
    )
    .slice(0, 8);

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col px-6 pb-16 pt-10">
      <header className="animate-rise mb-10">
        <p className="font-mono text-xs uppercase tracking-[0.28em] text-teal">
          Live DB stats · OpenAI reasoner · Any migration
        </p>
        <h1 className="mt-4 max-w-3xl text-5xl font-semibold tracking-tight text-ink md:text-6xl">
          SchemaSentinel
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-relaxed text-slateish/80">
          Paste or upload a real migration. Risk scores use live table sizes from your
          target database, then OpenAI explains blast radius without changing severity.
        </p>
        <div className="mt-5 flex flex-wrap gap-2 font-mono text-[11px]">
          <span className="rounded-md bg-white/70 px-2.5 py-1 ring-1 ring-ink/10">
            stats: {stats?.source || "…"}
            {stats?.url_host ? ` · ${stats.url_host}` : ""}
          </span>
          <span className="rounded-md bg-white/70 px-2.5 py-1 ring-1 ring-ink/10">
            LLM: {useOpenai ? "openai" : "mock"}
          </span>
        </div>
        <div className="mt-6 h-1 w-44 origin-left animate-pulsebar rounded-full bg-gradient-to-r from-teal via-ice to-transparent" />
      </header>

      <section
        className="animate-rise grid gap-8 lg:grid-cols-[1.2fr_0.8fr]"
        style={{ animationDelay: "60ms" }}
      >
        <form
          onSubmit={onAnalyze}
          className="rounded-2xl border border-ink/10 bg-white/75 p-6 shadow-panel backdrop-blur"
        >
          <h2 className="text-xl font-semibold">Analyze your migration</h2>
          <p className="mt-2 text-sm text-slateish/70">
            SQL, Alembic, Prisma, or Django — paste text or upload a file.
          </p>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="block font-mono text-[11px] uppercase tracking-wider text-slateish/60">
                Title
              </label>
              <input
                className="mt-2 w-full rounded-xl border border-ink/15 bg-foam/60 px-3 py-2.5 text-sm outline-none ring-teal focus:ring-2"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Release 2026-10 users email"
              />
            </div>
            <div>
              <label className="block font-mono text-[11px] uppercase tracking-wider text-slateish/60">
                Source type
              </label>
              <select
                className="mt-2 w-full rounded-xl border border-ink/15 bg-foam/60 px-3 py-2.5 text-sm outline-none ring-teal focus:ring-2"
                value={sourceType}
                onChange={(e) => setSourceType(e.target.value)}
              >
                <option value="auto">auto-detect</option>
                <option value="sql">sql</option>
                <option value="alembic">alembic</option>
                <option value="prisma">prisma</option>
                <option value="django">django</option>
              </select>
            </div>
          </div>

          <label className="mt-5 block font-mono text-[11px] uppercase tracking-wider text-slateish/60">
            Migration content
          </label>
          <textarea
            className="mt-2 h-52 w-full rounded-xl border border-ink/15 bg-foam/60 px-3 py-3 font-mono text-xs outline-none ring-teal focus:ring-2"
            placeholder={`ALTER TABLE users\n  ADD COLUMN email varchar(255) NOT NULL;`}
            value={sql}
            onChange={(e) => setSql(e.target.value)}
          />

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={pending || !sql.trim()}
              className="inline-flex items-center justify-center rounded-xl bg-ink px-5 py-3 text-sm font-medium text-foam transition hover:bg-slateish disabled:opacity-50"
            >
              {pending ? "Analyzing…" : "Run risk analysis"}
            </button>
            <label className="cursor-pointer rounded-xl border border-ink/15 bg-white px-4 py-3 text-sm text-slateish hover:border-teal/40">
              Upload .sql / .py
              <input
                type="file"
                accept=".sql,.py,.prisma,.txt"
                className="hidden"
                onChange={(e) => onUpload(e.target.files?.[0] || null)}
              />
            </label>
          </div>

          {error ? (
            <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 font-mono text-xs text-danger">
              {error}
            </p>
          ) : null}

          <div className="mt-8">
            <p className="font-mono text-[11px] uppercase tracking-wider text-slateish/55">
              Example library ({samples.length} files) — click to load into editor
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {samples.map((s) => (
                <button
                  key={s.filename}
                  type="button"
                  onClick={() => loadSample(s)}
                  className="rounded-lg border border-ink/10 bg-foam/70 px-3 py-2 text-left text-xs transition hover:border-teal/40"
                  title={s.preview}
                >
                  <span className="font-medium text-ink">{s.filename}</span>
                  <span className="ml-2 font-mono text-[10px] text-slateish/55">
                    {s.source_type}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </form>

        <aside className="space-y-6">
          <div className="rounded-2xl border border-ink/10 bg-white/70 p-5 shadow-panel backdrop-blur">
            <h2 className="text-lg font-semibold">Live target database</h2>
            <p className="mt-1 text-sm text-slateish/65">
              Row estimates from <code className="font-mono text-xs">TARGET_DATABASE_URL</code>
              {stats?.error ? ` · fallback: ${stats.error.slice(0, 80)}` : ""}
            </p>
            {liveTables.length === 0 ? (
              <p className="mt-4 text-sm text-slateish/60">No table stats yet.</p>
            ) : (
              <ul className="mt-4 space-y-2">
                {liveTables.map((t) => (
                  <li
                    key={`${t.schema_name}.${t.table_name}`}
                    className="flex items-center justify-between rounded-lg bg-foam/60 px-3 py-2 font-mono text-xs"
                  >
                    <span>
                      {t.schema_name}.{t.table_name}
                    </span>
                    <span className="text-slateish/70">
                      {formatRows(t.row_estimate)} rows · {formatBytes(t.size_bytes)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-2xl border border-ink/10 bg-white/60 p-5 backdrop-blur">
            <h2 className="text-lg font-semibold">Recent analyses</h2>
            <ul className="mt-4 space-y-3">
              {analyses.length === 0 ? (
                <li className="text-sm text-slateish/60">
                  No analyses yet — paste SQL or upload a file.
                </li>
              ) : (
                analyses.slice(0, 8).map((a) => (
                  <li key={a.id}>
                    <Link
                      href={`/analyses/${a.id}`}
                      className="flex items-start justify-between gap-3 rounded-xl border border-ink/5 bg-foam/50 px-3 py-3 transition hover:border-teal/30"
                    >
                      <div>
                        <p className="text-sm font-medium">{a.title}</p>
                        <p className="mt-1 font-mono text-[11px] text-slateish/55">
                          {a.source_type} · score {a.overall_score?.toFixed(2) ?? "—"}
                        </p>
                      </div>
                      <RiskBadge value={a.overall_risk || a.status} />
                    </Link>
                  </li>
                ))
              )}
            </ul>
          </div>
        </aside>
      </section>
    </main>
  );
}
