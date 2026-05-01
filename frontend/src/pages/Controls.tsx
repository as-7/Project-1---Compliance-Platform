import { useEffect, useMemo, useState } from "react";
import { RegulatoryControl, listRegulatoryControls } from "../api/client";

const FRAMEWORKS = ["", "SOC2", "ISO27001", "GDPR", "HIPAA", "OTHER"];
const SEVERITIES = ["", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

const SEV_TONE: Record<string, string> = {
  LOW: "bg-emerald-100 text-emerald-700",
  MEDIUM: "bg-amber-100 text-amber-700",
  HIGH: "bg-orange-100 text-orange-700",
  CRITICAL: "bg-rose-100 text-rose-700",
};

export default function Controls() {
  const [items, setItems] = useState<RegulatoryControl[]>([]);
  const [framework, setFramework] = useState("");
  const [severity, setSeverity] = useState("");
  const [riskDomain, setRiskDomain] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await listRegulatoryControls({
          framework: framework || undefined,
          severity: severity || undefined,
          risk_domain: riskDomain || undefined,
          limit: "500",
        });
        if (!cancelled) setItems(r.items);
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
  }, [framework, severity, riskDomain]);

  const grouped = useMemo(() => {
    const out: Record<string, RegulatoryControl[]> = {};
    for (const c of items) {
      out[c.risk_domain] = out[c.risk_domain] ?? [];
      out[c.risk_domain].push(c);
    }
    return out;
  }, [items]);

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-3 flex flex-wrap gap-3">
        <Select label="Framework" value={framework} onChange={setFramework} options={FRAMEWORKS} />
        <Select label="Severity" value={severity} onChange={setSeverity} options={SEVERITIES} />
        <Input label="Risk domain" value={riskDomain} onChange={setRiskDomain} placeholder="e.g. Access Control" />
        <div className="ml-auto self-end text-sm text-slate-500">
          {items.length} controls
        </div>
      </div>

      <div className="space-y-4">
        {Object.entries(grouped).map(([domain, list]) => (
          <div key={domain} className="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-4 py-2 bg-slate-50 text-slate-700 text-sm font-medium">
              {domain} <span className="text-slate-400">· {list.length}</span>
            </div>
            <table className="w-full text-sm">
              <tbody>
                {list.map((c) => (
                  <tr key={c.id} className="border-t border-slate-100 align-top">
                    <td className="px-4 py-2 w-32">
                      <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                        {c.framework}
                      </span>
                    </td>
                    <td className="px-4 py-2 w-24">
                      <span className={`text-xs px-2 py-0.5 rounded ${SEV_TONE[c.severity]}`}>
                        {c.severity}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <div className="font-medium text-slate-900">{c.title}</div>
                      <div className="text-slate-600 text-xs mt-1 line-clamp-2">{c.description}</div>
                      <div className="text-slate-400 text-[11px] mt-1">
                        chunk {c.source_chunk_id}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        {items.length === 0 && (
          <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8 text-center text-slate-500">
            No controls extracted yet. Wait for the agent to finish ingestion, or upload a document.
          </div>
        )}
      </div>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="text-sm">
      <div className="text-xs text-slate-500 mb-0.5">{label}</div>
      <select
        className="border border-slate-300 rounded px-2 py-1 text-sm bg-white"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o || "All"}
          </option>
        ))}
      </select>
    </label>
  );
}

function Input({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="text-sm">
      <div className="text-xs text-slate-500 mb-0.5">{label}</div>
      <input
        type="text"
        className="border border-slate-300 rounded px-2 py-1 text-sm bg-white"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}
