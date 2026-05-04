import type {
  MonitoringAlert,
  MonitoringConfig,
  MonitoringCustomer,
  MonitoringRun,
} from "@/types/monitoring";

const BASE = "/api/monitoring";

export async function listCustomers(): Promise<MonitoringCustomer[]> {
  const res = await fetch(`${BASE}/customers`);
  const data = (await res.json()) as { customers: MonitoringCustomer[] };
  return data.customers;
}

export async function createCustomer(payload: {
  ts_code: string;
  name: string;
  industry: string;
}): Promise<MonitoringCustomer> {
  const res = await fetch(`${BASE}/customers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await res.json()) as MonitoringCustomer;
}

export async function deleteCustomer(id: string): Promise<void> {
  await fetch(`${BASE}/customers/${id}`, { method: "DELETE" });
}

export async function listAlerts(customerId?: string): Promise<MonitoringAlert[]> {
  const url = customerId
    ? `${BASE}/alerts?customer_id=${customerId}`
    : `${BASE}/alerts`;
  const res = await fetch(url);
  const data = (await res.json()) as { alerts: MonitoringAlert[] };
  return data.alerts;
}

export async function getAlert(aid: string): Promise<{
  id: string;
  alert_level: string;
  report_markdown: string;
  deep_dive_text: string | null;
  escalation_status: string | null;
  report_json: Record<string, unknown>;
}> {
  const res = await fetch(`${BASE}/alerts/${aid}`);
  if (!res.ok) throw new Error(`alert ${aid} not found`);
  return (await res.json()) as {
    id: string;
    alert_level: string;
    report_markdown: string;
    deep_dive_text: string | null;
    escalation_status: string | null;
    report_json: Record<string, unknown>;
  };
}

export async function listRuns(customerId?: string): Promise<MonitoringRun[]> {
  const url = customerId
    ? `${BASE}/runs?customer_id=${customerId}`
    : `${BASE}/runs`;
  const res = await fetch(url);
  const data = (await res.json()) as { runs: MonitoringRun[] };
  return data.runs;
}

export async function triggerScan(customerIds: string[]): Promise<void> {
  await fetch(`${BASE}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_ids: customerIds }),
  });
}

export async function updateCustomer(
  id: string,
  payload: Partial<Pick<MonitoringCustomer, "ts_code" | "name" | "industry" | "enabled">>,
): Promise<MonitoringCustomer> {
  const res = await fetch(`${BASE}/customers/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`updateCustomer ${id} failed: ${res.status}`);
  return (await res.json()) as MonitoringCustomer;
}

export async function getConfig(): Promise<MonitoringConfig> {
  const res = await fetch(`${BASE}/config`);
  return (await res.json()) as MonitoringConfig;
}
