import { useEffect, useState } from "react";
import { GapSummary, gapSummary } from "../api/client";

const FRAMEWORKS = ["SOC2", "ISO27001", "GDPR", "HIPAA", "OTHER"];
const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

function statusColor(missing: number, partial: number, covered: number) {
  const total = missing + partial + covered;
  if (total === 0) return "bg-slate-100 text-slate-400";
  const missingPct = missing / total;
  const partialPct = partial / total;
  if (missingPct >= 0.5) return "bg-rose-200 text-rose-900";
  if (missingPct > 0) return "bg-orange-200 text-orange-900";
  if (partialPct > 0) return "bg-amber-200 text-amber-900";
  return "bg-emerald-200 text-emerald-900";
}

export default function Gaps() {
  const [summary, setSummary] = useState<GapSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const s = await gapSummary();
        if (!cancelled) setSummary(s);
      } catch {
        /* ignore */
      }
    }
    load();
    const t = setInterval(load, 6000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const grid: Record<string, Record<string, { covered: number; partial: number; missing: number }>> = {};
  for (const fw of FRAMEWORKS) {
    grid[fw] = {};
    for (const sv of SEVERITIES) grid[fw][sv] = { covered: 0, partial: 0, missing: 0 };
  }
  for (const row of summary?.by_framework ?? []) {
    if (!grid[row.framework] || !grid[row.framework][row.severity]) continue;
    grid[row.framework][row.severity] = {
      covered: row.covered,
      partial: row.partial,
      missing: row.missing,
    };
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg border border-slate-200 p-6 shadow-sm flex items-center gap-8">
        <div>
          <div className="text-xs uppercase text-slate-500">Total regulatory controls</div>
          <div className="text-3xl font-semibold">{summary?.total_regulatory_controls ?? 0}</div>
        </div>
        <div>
          <div className="text-xs uppercase text-slate-500">Total org controls</div>
          <div className="text-3xl font-semibold">{summary?.total_org_controls ?? 0}</div>
        </div>
        <div>
          <div className="text-xs uppercase text-slate-500">Coverage</div>
          <div className="text-3xl font-semibold">
            {summary ? Math.round(summary.coverage_pct * 100) : 0}%
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
        <div className="text-sm font-medium text-slate-700 mb-3">
          Gap heatmap — missing/partial/covered by framework × severity
        </div>
        <div className="overflow-x-auto">
          <table className="border-collapse">
            <thead>
              <tr>
                <th className="text-xs text-slate-500 font-normal text-left pr-3 pb-2"></th>
                {SEVERITIES.map((sv) => (
                  <th key={sv} className="text-xs text-slate-500 font-normal px-2 pb-2">
                    {sv}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FRAMEWORKS.map((fw) => (
                <tr key={fw}>
                  <td className="text-sm text-slate-700 pr-3 py-1 align-middle">{fw}</td>
                  {SEVERITIES.map((sv) => {
                    const cell = grid[fw][sv];
                    const total = cell.covered + cell.partial + cell.missing;
                    return (
                      <td key={sv} className="px-1 py-1">
                        <div
                          className={`w-28 h-16 rounded ${statusColor(
                            cell.missing,
                            cell.partial,
                            cell.covered,
                          )} flex flex-col items-center justify-center text-xs`}
                          title={`${total} controls`}
                        >
                          <div className="font-semibold">{total}</div>
                          <div className="opacity-80">
                            {cell.covered}/{cell.partial}/{cell.missing}
                          </div>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-[11px] text-slate-500 mt-2">
          Cell legend: <span className="font-medium">total</span> · covered / partial / missing
        </div>
      </div>
    </div>
  );
}
