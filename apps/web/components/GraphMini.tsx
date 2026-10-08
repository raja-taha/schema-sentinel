type Node = { id: string; kind?: string; name?: string; path?: string };
type Edge = { source: string; target: string; relation?: string };

export function GraphMini({
  nodes = [],
  edges = [],
}: {
  nodes?: Node[];
  edges?: Edge[];
}) {
  const visible = nodes.slice(0, 12);
  const width = 520;
  const height = 180;
  const cols = Math.max(3, Math.ceil(Math.sqrt(visible.length || 1)));

  const positions = visible.map((n, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    return {
      id: n.id,
      x: 40 + col * (width / cols),
      y: 36 + row * 52,
      label: n.name || n.path || n.id.replace(/^[^:]+:/, "").slice(0, 18),
      kind: n.kind || "node",
    };
  });
  const posMap = Object.fromEntries(positions.map((p) => [p.id, p]));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full overflow-visible">
      {edges
        .filter((e) => posMap[e.source] && posMap[e.target])
        .slice(0, 24)
        .map((e, i) => {
          const a = posMap[e.source];
          const b = posMap[e.target];
          return (
            <line
              key={`${e.source}-${e.target}-${i}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="rgba(13,148,136,0.35)"
              strokeWidth="1.5"
              className="animate-draw"
              strokeDasharray="240"
            />
          );
        })}
      {positions.map((p) => (
        <g key={p.id} className="animate-rise">
          <circle
            cx={p.x}
            cy={p.y}
            r={p.kind === "code" ? 7 : 9}
            fill={p.kind === "operation" ? "#38bdf8" : p.kind === "code" ? "#d97706" : "#0d9488"}
            opacity={0.9}
          />
          <text
            x={p.x + 12}
            y={p.y + 4}
            className="fill-slateish"
            style={{ fontSize: 10, fontFamily: "var(--font-plex)" }}
          >
            {p.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
