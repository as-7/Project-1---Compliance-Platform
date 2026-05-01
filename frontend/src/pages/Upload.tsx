import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DocumentRead, listDocuments, uploadDocument } from "../api/client";

const STATUS_TONE: Record<DocumentRead["status"], string> = {
  UPLOADED: "bg-slate-100 text-slate-700",
  INGESTING: "bg-blue-100 text-blue-700",
  EXTRACTING: "bg-amber-100 text-amber-700",
  READY: "bg-emerald-100 text-emerald-700",
  FAILED: "bg-rose-100 text-rose-700",
};

export default function Upload() {
  const [documents, setDocuments] = useState<DocumentRead[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const r = await listDocuments();
      setDocuments(r.items);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  const inProgress = documents.some((d) =>
    ["UPLOADED", "INGESTING", "EXTRACTING"].includes(d.status),
  );

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!inProgress) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [inProgress]);

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      await uploadDocument(file);
      await refresh();
    } catch (ex: any) {
      setErr(ex.message);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg border border-slate-200 p-6 shadow-sm">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-lg font-medium text-slate-900">Upload regulatory document</div>
            <div className="text-sm text-slate-500 mt-1">
              Accepts PDF, plain text, or markdown. Extraction starts automatically.
            </div>
          </div>
          <label className="inline-flex items-center bg-slate-900 text-white text-sm rounded px-4 py-2 cursor-pointer hover:bg-slate-800">
            <input
              type="file"
              accept=".pdf,.txt,.md"
              className="hidden"
              onChange={onPick}
              disabled={busy}
            />
            {busy ? "Uploading…" : "Choose file"}
          </label>
        </div>
        {err && <div className="mt-3 text-sm text-rose-600">{err}</div>}
      </div>

      <div className="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wide">
            <tr>
              <th className="text-left px-4 py-2">Name</th>
              <th className="text-left px-4 py-2">Status</th>
              <th className="text-right px-4 py-2">Pages</th>
              <th className="text-right px-4 py-2">Chunks</th>
              <th className="text-left px-4 py-2">Uploaded</th>
              <th className="text-right px-4 py-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((d) => {
              const ready = d.status === "READY";
              return (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="px-4 py-2 text-slate-900">{d.name}</td>
                  <td className="px-4 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded ${STATUS_TONE[d.status]}`}>
                      {d.status}
                    </span>
                    {d.error_message && (
                      <span className="ml-2 text-xs text-rose-600" title={d.error_message}>
                        (error)
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">{d.page_count ?? "—"}</td>
                  <td className="px-4 py-2 text-right">{d.chunk_count ?? "—"}</td>
                  <td className="px-4 py-2 text-slate-500">
                    {new Date(d.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {ready ? (
                      <Link
                        to={`/chat?docId=${d.id}&docName=${encodeURIComponent(d.name)}`}
                        className="inline-flex items-center bg-slate-900 text-white text-xs rounded px-3 py-1 hover:bg-slate-800"
                      >
                        Start Q&amp;A
                      </Link>
                    ) : (
                      <span
                        className="inline-flex items-center bg-slate-100 text-slate-400 text-xs rounded px-3 py-1 cursor-not-allowed"
                        title="Available once extraction completes"
                      >
                        Start Q&amp;A
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
            {documents.length === 0 && (
              <tr>
                <td className="px-4 py-6 text-slate-500 text-center" colSpan={6}>
                  No documents yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
