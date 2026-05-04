export type AlertLevel = "green" | "yellow" | "red";

export interface MonitoringCustomer {
  id: string;
  ts_code: string;
  name: string;
  industry: string;
  enabled: boolean;
  thresholds_override?: Record<string, number> | null;
}

export interface MonitoringRun {
  id: string;
  customer_id: string;
  trigger_type: "cron" | "disclosure_event" | "manual";
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "failed";
}

export interface MonitoringAlert {
  id: string;
  run_id: string;
  customer_id: string;
  alert_level: AlertLevel;
  created_at: string;
}

export interface MonitoringConfig {
  scan_time: string;
  daily_budget_cny: number;
  thresholds: Record<string, Record<string, number>>;
}
