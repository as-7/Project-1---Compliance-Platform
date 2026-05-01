import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  PieChart,
  Pie,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  DocumentRead,
  GapSummary,
  gapSummary,
  listDocuments,
  listRegulatoryControls,
} from "../api/client";

const SEV_COLOR = { LOW: "#16a34a", MEDIUM: "#ca8a04", HIGH: "#ea580c", CRITICAL: "#dc2626" } as const;

export default function Dashboard() {
  const [summary, setSummary] = useState<GapSummary | null>(null);
  const [byFramework, setByFramework] = useState<Record<string, number>>({});
  const [bySeverity, setBySeverity] = useState<Record<string, number>>({});
  const [docCount, setDocCount] = useState(0);
  const [inProgress, setInProgress] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [s, ctrls, docs] = await Promise.all([
        gapSummary().catch(() => null),
        listRegulatoryControls({ limit: "1000" }).catch(() => ({ items: [], total: 0 })),
        listDocuments().catch(() => ({ items: [] as DocumentRead[], total: 0 })),
      ]);
      if (cancelled) return;
      if (s) setSummary(s);
      const fw: Record<string, number> = {};
      const sv: Record<string, number> = {};
      for (const c of ctrls.items) {
        fw[c.framework] = (fw[c.framework] ?? 0) + 1;
        sv[c.severity] = (sv[c.severity] ?? 0) + 1;
      }
      setByFramework(fw);
      setBySeverity(sv);
      setDocCount(docs.total);
      setInProgress(
        docs.items.some((d) =>
          ["UPLOADED", "INGESTING", "EXTRACTING"].includes(d.status),
        ),
      );
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!inProgress) return;
    let cancelled = false;
    const t = setInterval(async () => {
      const [s, ctrls, docs] = await Promise.all([
        gapSummary().catch(() => null),
        listRegulatoryControls({ limit: "1000" }).catch(() => ({ items: [], total: 0 })),
        listDocuments().catch(() => ({ items: [] as DocumentRead[], total: 0 })),
      ]);
      if (cancelled) return;
      if (s) setSummary(s);
      const fw: Record<string, number> = {};
      const sv: Record<string, number> = {};
      for (const c of ctrls.items) {
        fw[c.framework] = (fw[c.framework] ?? 0) + 1;
        sv[c.severity] = (sv[c.severity] ?? 0) + 1;
      }
      setByFramework(fw);
      setBySeverity(sv);
      setDocCount(docs.total);
      setInProgress(
        docs.items.some((d) =>
          ["UPLOADED", "INGESTING", "EXTRACTING"].includes(d.status),
        ),
      );
    }, 7000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [inProgress]);

  const fwData = Object.entries(byFramework).map(([framework, count]) => ({ framework, count }));
  const sevData = Object.entries(bySeverity).map(([severity, value]) => ({
    severity,
    value,
    fill: (SEV_COLOR as Record<string, string>)[severity] ?? "#64748b",
  }));

  const coveragePct = summary ? Math.round(summary.coverage_pct * 100) : 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat label="Documents ingested" value={docCount} />
        <Stat label="Regulatory controls" value={summary?.total_regulatory_controls ?? 0} />
        <Stat label="Organization controls" value={summary?.total_org_controls ?? 0} />
        <Stat label="Coverage" value={`${coveragePct}%`} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="Controls by framework">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={fwData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="framework" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="#1e3a8a" />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Severity distribution">
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={sevData}
                dataKey="value"
                nameKey="severity"
                cx="50%"
                cy="50%"
                outerRadius={90}
                label
              >
                {sevData.map((d, i) => (
                  <Cell key={i} fill={d.fill} />
                ))}
              </Pie>
              <Legend />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
      <div className="text-xs uppercase text-slate-500 tracking-wide">{label}</div>
      <div className="text-3xl font-semibold mt-1 text-slate-900">{value}</div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
      <div className="text-sm font-medium text-slate-700 mb-2">{title}</div>
      {children}
    </div>
  );
}
