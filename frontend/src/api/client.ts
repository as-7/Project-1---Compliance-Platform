export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8080";

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} failed: ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export type DocumentRead = {
  id: string;
  name: string;
  status: "UPLOADED" | "INGESTING" | "EXTRACTING" | "READY" | "FAILED";
  page_count: number | null;
  chunk_count: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type RegulatoryControl = {
  id: string;
  document_id: string;
  title: string;
  description: string;
  framework: "SOC2" | "ISO27001" | "GDPR" | "HIPAA" | "OTHER";
  risk_domain: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  source_chunk_id: string;
  source_quote: string;
  created_at: string;
};

export type OrganizationControl = {
  id: string;
  code: string;
  title: string;
  description: string;
  risk_domain: string;
  owner: string | null;
  evidence_url: string | null;
  created_at: string;
};

export type GapSummary = {
  by_framework: Array<{
    framework: string;
    severity: string;
    covered: number;
    partial: number;
    missing: number;
  }>;
  total_regulatory_controls: number;
  total_org_controls: number;
  coverage_pct: number;
};

export async function listDocuments(): Promise<{ items: DocumentRead[]; total: number }> {
  return api(`/api/documents`);
}

export async function listRegulatoryControls(params: Record<string, string | undefined> = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v) as [string, string][],
  ).toString();
  return api<{ items: RegulatoryControl[]; total: number }>(`/api/controls/regulatory?${qs}`);
}

export async function listOrganizationControls() {
  return api<OrganizationControl[]>(`/api/controls/organization`);
}

export async function gapSummary() {
  return api<GapSummary>(`/api/gaps/summary`);
}

export async function uploadDocument(file: File) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API_BASE}/api/documents`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}
