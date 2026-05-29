/**
 * Monitoring API client — v1.0 contract.
 *
 * Live endpoints (backend/app/router/monitoring_router.py):
 *   GET  /api/monitoring/signals               list user's alerts
 *   GET  /api/monitoring/signals/{aid}/detail  single alert detail
 *   POST /api/monitoring/refresh               trigger detection_cycle
 *
 * All v0.x endpoints (customers / runs / scan / alerts / config) have been
 * removed from the backend.  Stubs for types that other modules still import
 * (MonitoringCustomer, MonitoringRun) are kept below so callers compile, but
 * the functions that hit dead endpoints are replaced with the live equivalents.
 */
import type { AlertLevel } from "@/types/monitoring";
import { getAuthToken } from "./auth-token";

const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").replace(/\/$/, "");
const BASE = `${API_BASE}/api/monitoring`;

// ---------------------------------------------------------------------------
// Shared auth header helper
// ---------------------------------------------------------------------------

function authHeader(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ---------------------------------------------------------------------------
// Live v1.0 types (align with SignalSummaryOut / SignalDetailOut)
// ---------------------------------------------------------------------------

export interface SignalSummary {
  id: string;
  run_id: string;
  ts_code: string;
  alert_level: AlertLevel;
  detail_status: string;
  created_at: string | null;
}

export interface SignalDetail {
  id: string;
  ts_code: string;
  alert_level: AlertLevel;
  detail_status: string;
  report_json: Record<string, unknown>;
  report_markdown: string | null;
  error_message: string | null;
  created_at: string | null;
}

// ---------------------------------------------------------------------------
// Live endpoints
// ---------------------------------------------------------------------------

/**
 * GET /api/monitoring/signals — list current user's monitoring alerts.
 * Replaces the removed listAlerts() / listCustomers() / listRuns() combo.
 */
export async function listSignals(limit = 50): Promise<SignalSummary[]> {
  const res = await fetch(`${BASE}/signals?limit=${limit}`, {
    headers: { ...authHeader() },
  });
  if (!res.ok) {
    throw new Error(`listSignals failed: ${res.status} ${res.statusText}`);
  }
  const data = (await res.json()) as { signals: SignalSummary[] };
  return data.signals;
}

/**
 * GET /api/monitoring/signals/{aid}/detail — single alert detail.
 * Replaces the removed getAlert() (which hit /alerts/{aid}).
 */
export async function getSignalDetail(aid: string): Promise<SignalDetail> {
  const res = await fetch(`${BASE}/signals/${aid}/detail`, {
    headers: { ...authHeader() },
  });
  if (!res.ok) {
    throw new Error(`getSignalDetail ${aid} failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as SignalDetail;
}

/**
 * POST /api/monitoring/refresh — trigger detection_cycle for current user.
 * Replaces the removed triggerScan() (which hit /runs).
 */
export async function triggerRefresh(): Promise<{ task_id: string; status: string }> {
  const res = await fetch(`${BASE}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
  });
  if (!res.ok) {
    throw new Error(`triggerRefresh failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as { task_id: string; status: string };
}

// ---------------------------------------------------------------------------
// getAlert — kept as named export for alert-detail.tsx compatibility.
// Internally delegates to getSignalDetail (live /signals/{aid}/detail endpoint).
// Returns the same shape alert-detail.tsx expects, mapping missing fields to null.
// ---------------------------------------------------------------------------

export async function getAlert(aid: string): Promise<{
  id: string;
  alert_level: string;
  report_markdown: string;
  deep_dive_text: string | null;
  escalation_status: string | null;
  report_json: Record<string, unknown>;
}> {
  const d = await getSignalDetail(aid);
  return {
    id: d.id,
    alert_level: d.alert_level,
    report_markdown: d.report_markdown ?? "",
    // SignalDetailOut does not expose deep_dive_text / escalation_status;
    // those fields may be inside report_json if the backend embeds them.
    deep_dive_text:
      typeof d.report_json.deep_dive_text === "string"
        ? d.report_json.deep_dive_text
        : null,
    escalation_status:
      typeof d.report_json.escalation_status === "string"
        ? d.report_json.escalation_status
        : null,
    report_json: d.report_json,
  };
}
