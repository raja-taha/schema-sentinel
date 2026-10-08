const STYLES: Record<string, string> = {
  critical: "bg-danger/10 text-danger ring-danger/20",
  high: "bg-orange-500/10 text-orange-700 ring-orange-500/20",
  medium: "bg-warn/10 text-warn ring-warn/25",
  low: "bg-safe/10 text-safe ring-safe/20",
  pending: "bg-slateish/10 text-slateish ring-slateish/15",
  running: "bg-ice/10 text-sky-700 ring-ice/25",
  completed: "bg-teal/10 text-teal ring-teal/20",
  failed: "bg-danger/10 text-danger ring-danger/20",
};

export function RiskBadge({ value }: { value: string | null | undefined }) {
  const key = (value || "pending").toLowerCase();
  const cls = STYLES[key] || STYLES.pending;
  return (
    <span
      className={`inline-flex items-center rounded-md px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider ring-1 ${cls}`}
    >
      {value || "pending"}
    </span>
  );
}
