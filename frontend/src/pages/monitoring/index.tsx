import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Badge,
  Button,
  Col,
  Empty,
  Input,
  message,
  Row,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  AlertOutlined,
  SyncOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { Link } from "react-router-dom";
import {
  listAlerts,
  listCustomers,
  listRuns,
  triggerScan,
} from "@/api/monitoring";
import type {
  AlertLevel,
  MonitoringAlert,
  MonitoringCustomer,
  MonitoringRun,
} from "@/types/monitoring";

// ── Design tokens (aligned with Perplexity Finance / 同花顺, v0.8.3-pre) ──
const TOKEN = {
  pageBg: "#faf9f7",          // 米色底
  cardBg: "#ffffff",
  borderColor: "#e8e4dc",
  textPrimary: "#1a1d21",
  textSecondary: "#5d6875",
  textTertiary: "#8a96a3",
  accentRed: "#c0392b",       // 赭红 — 红 alert 强调
  accentYellow: "#b8860b",    // 深金黄 — 黄 alert
  accentGreen: "#27875a",     // 深绿 — 正常状态
  monoFont: '"SF Mono", "JetBrains Mono", Consolas, monospace',
};

const POLL_MS = 5000;

// ── Alert level mapping ──
const LEVEL_BADGE_STATUS: Record<AlertLevel, "success" | "warning" | "error"> = {
  green: "success",
  yellow: "warning",
  red: "error",
};

const LEVEL_LABEL: Record<AlertLevel, string> = {
  green: "正常",
  yellow: "预警",
  red: "告警",
};

const LEVEL_COLOR: Record<AlertLevel, string> = {
  green: TOKEN.accentGreen,
  yellow: TOKEN.accentYellow,
  red: TOKEN.accentRed,
};

// ── Stat Card sub-component (hardware-accelerated, hover lift) ──
interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  valueColor?: string;
  loading: boolean;
}

function StatCard({ icon, label, value, valueColor, loading }: StatCardProps) {
  return (
    <div
      style={{
        backgroundColor: TOKEN.cardBg,
        border: `1px solid ${TOKEN.borderColor}`,
        borderRadius: 8,
        padding: "20px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        // Hardware acceleration
        willChange: "transform",
        transform: "translateZ(0)",
        backfaceVisibility: "hidden",
        transition: "transform 0.2s cubic-bezier(0.16,1,0.3,1), box-shadow 0.2s cubic-bezier(0.16,1,0.3,1)",
        cursor: "default",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLDivElement).style.transform = "translateY(-2px) translateZ(0)";
        (e.currentTarget as HTMLDivElement).style.boxShadow = "0 4px 12px rgba(0,0,0,0.08)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.transform = "translateZ(0)";
        (e.currentTarget as HTMLDivElement).style.boxShadow = "none";
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 12,
          color: TOKEN.textTertiary,
          letterSpacing: "0.02em",
        }}
      >
        {icon}
        <span>{label}</span>
      </div>
      {loading ? (
        <Skeleton.Input active size="small" style={{ width: 60, height: 28 }} />
      ) : (
        <div
          style={{
            fontSize: 28,
            fontWeight: 600,
            fontFamily: TOKEN.monoFont,
            color: valueColor ?? TOKEN.textPrimary,
            lineHeight: 1,
          }}
        >
          {value}
        </div>
      )}
    </div>
  );
}

// ── Alert level status dot ──
function AlertDot({ level }: { level: AlertLevel }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <Badge
        status={LEVEL_BADGE_STATUS[level]}
        color={level === "yellow" ? TOKEN.accentYellow : undefined}
      />
      <span
        style={{
          fontSize: 13,
          color: LEVEL_COLOR[level],
          fontWeight: 500,
        }}
      >
        {LEVEL_LABEL[level]}
      </span>
    </div>
  );
}

// ── Main page component ──
export default function MonitoringIndex() {
  const [customers, setCustomers] = useState<MonitoringCustomer[]>([]);
  const [alerts, setAlerts] = useState<MonitoringAlert[]>([]);
  const [runs, setRuns] = useState<MonitoringRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [search, setSearch] = useState("");
  const [industryFilter, setIndustryFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<"all" | "enabled" | "disabled">("all");

  const refresh = useCallback(async () => {
    try {
      const [c, a, r] = await Promise.all([
        listCustomers(),
        listAlerts(),
        listRuns(),
      ]);
      setCustomers(c);
      setAlerts(a);
      setRuns(r);
    } catch (err) {
      console.error("[MonitoringIndex] refresh error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + 5s polling
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  // ── Derived stats ──
  const stats = useMemo(() => {
    const since24h = Date.now() - 24 * 3600 * 1000;
    const recent = alerts.filter(
      (a) => new Date(a.created_at).getTime() > since24h,
    );
    const todayStr = new Date().toDateString();
    const todayRuns = runs.filter(
      (r) => new Date(r.started_at).toDateString() === todayStr,
    );
    return {
      total: customers.length,
      todayScans: todayRuns.length,
      yellow24h: recent.filter((a) => a.alert_level === "yellow").length,
      red24h: recent.filter((a) => a.alert_level === "red").length,
    };
  }, [customers, alerts, runs]);

  // ── Per-customer highest alert level (last 24h) ──
  const customerLevelMap = useMemo(() => {
    const since24h = Date.now() - 24 * 3600 * 1000;
    const recent = alerts.filter(
      (a) => new Date(a.created_at).getTime() > since24h,
    );
    const PRIORITY: Record<AlertLevel, number> = { green: 0, yellow: 1, red: 2 };
    const m: Record<string, AlertLevel> = {};
    for (const a of recent) {
      const cur = m[a.customer_id];
      if (!cur || PRIORITY[a.alert_level] > PRIORITY[cur]) {
        m[a.customer_id] = a.alert_level;
      }
    }
    return m;
  }, [alerts]);

  // ── Per-customer latest scan time ──
  const customerLatestRunMap = useMemo(() => {
    const m: Record<string, string> = {};
    for (const r of runs) {
      const cur = m[r.customer_id];
      if (!cur || r.started_at > cur) {
        m[r.customer_id] = r.started_at;
      }
    }
    return m;
  }, [runs]);

  // ── 24h alert count per customer ──
  const customerAlertCountMap = useMemo(() => {
    const since24h = Date.now() - 24 * 3600 * 1000;
    const m: Record<string, number> = {};
    for (const a of alerts) {
      if (new Date(a.created_at).getTime() > since24h) {
        m[a.customer_id] = (m[a.customer_id] ?? 0) + 1;
      }
    }
    return m;
  }, [alerts]);

  // ── Latest alert ID per customer (for navigation to detail page) ──
  const customerLatestAlertIdMap = useMemo(() => {
    const idMap: Record<string, string> = {};
    const tsMap: Record<string, string> = {};
    for (const a of alerts) {
      const curTs = tsMap[a.customer_id];
      if (!curTs || a.created_at > curTs) {
        tsMap[a.customer_id] = a.created_at;
        idMap[a.customer_id] = a.id;
      }
    }
    return idMap;
  }, [alerts]);

  // ── Industry options ──
  const industryOptions = useMemo(() => {
    const set = new Set(customers.map((c) => c.industry));
    return Array.from(set).map((i) => ({ value: i, label: i }));
  }, [customers]);

  // ── Filtered customer list ──
  const filtered = useMemo(() => {
    return customers
      .filter(
        (c) =>
          !search ||
          c.name.toLowerCase().includes(search.toLowerCase()) ||
          c.ts_code.toLowerCase().includes(search.toLowerCase()),
      )
      .filter((c) => !industryFilter || c.industry === industryFilter)
      .filter((c) => {
        if (statusFilter === "enabled") return c.enabled;
        if (statusFilter === "disabled") return !c.enabled;
        return true;
      });
  }, [customers, search, industryFilter, statusFilter]);

  // ── Scan all filtered customers ──
  const handleScanAll = async () => {
    if (filtered.length === 0) {
      void message.warning("没有符合条件的客户");
      return;
    }
    setScanning(true);
    try {
      await triggerScan(filtered.map((c) => c.id));
      void message.success(`已触发 ${filtered.length.toString()} 位客户扫描`);
      // Optimistic: refresh after brief delay
      setTimeout(() => {
        void refresh();
      }, 800);
    } catch (err) {
      console.error("[MonitoringIndex] triggerScan error:", err);
      void message.error("触发扫描失败，请重试");
    } finally {
      setScanning(false);
    }
  };

  const handleScanOne = async (customerId: string) => {
    try {
      await triggerScan([customerId]);
      void message.success("已触发单客户扫描");
      setTimeout(() => {
        void refresh();
      }, 800);
    } catch (err) {
      console.error("[MonitoringIndex] triggerScanOne error:", err);
      void message.error("触发扫描失败");
    }
  };

  // ── Format datetime ──
  const formatTime = (iso: string | undefined): string => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  // ── Table columns ──
  const columns: ColumnsType<MonitoringCustomer> = [
    {
      title: "客户名",
      dataIndex: "name",
      key: "name",
      width: 140,
      render: (name: string, record: MonitoringCustomer) => (
        <Link
          to={`/monitoring/${record.id}`}
          style={{
            color: TOKEN.textPrimary,
            fontWeight: 500,
            transition: "color 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.color = TOKEN.accentRed;
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.color = TOKEN.textPrimary;
          }}
        >
          {name}
        </Link>
      ),
    },
    {
      title: "代码",
      dataIndex: "ts_code",
      key: "ts_code",
      width: 110,
      render: (code: string) => (
        <span
          style={{
            fontFamily: TOKEN.monoFont,
            fontSize: 12,
            color: TOKEN.textSecondary,
            letterSpacing: "0.04em",
          }}
        >
          {code}
        </span>
      ),
    },
    {
      title: "行业",
      dataIndex: "industry",
      key: "industry",
      width: 120,
      render: (industry: string) => (
        <Tag
          style={{
            borderColor: TOKEN.borderColor,
            color: TOKEN.textSecondary,
            backgroundColor: "#f5f2ec",
            fontSize: 12,
            borderRadius: 4,
          }}
        >
          {industry}
        </Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "enabled",
      key: "enabled",
      width: 80,
      render: (enabled: boolean) => (
        <Switch
          size="small"
          checked={enabled}
          disabled
          style={{ cursor: "default" }}
        />
      ),
    },
    {
      title: "最新扫描",
      key: "latest_run",
      width: 130,
      render: (_: unknown, record: MonitoringCustomer) => (
        <span
          style={{
            fontFamily: TOKEN.monoFont,
            fontSize: 12,
            color: TOKEN.textTertiary,
          }}
        >
          {formatTime(customerLatestRunMap[record.id])}
        </span>
      ),
    },
    {
      title: "预警等级",
      key: "alert_level",
      width: 100,
      render: (_: unknown, record: MonitoringCustomer) => {
        const level: AlertLevel = customerLevelMap[record.id] ?? "green";
        return <AlertDot level={level} />;
      },
    },
    {
      title: "24h 告警",
      key: "alert_count",
      width: 90,
      align: "center" as const,
      render: (_: unknown, record: MonitoringCustomer) => {
        const count = customerAlertCountMap[record.id] ?? 0;
        if (count === 0)
          return (
            <span style={{ color: TOKEN.textTertiary, fontFamily: TOKEN.monoFont }}>
              0
            </span>
          );
        const level = customerLevelMap[record.id] ?? "green";
        const latestAlertId = customerLatestAlertIdMap[record.id];
        const inner = (
          <span
            style={{
              fontFamily: TOKEN.monoFont,
              fontWeight: 600,
              color: LEVEL_COLOR[level],
            }}
          >
            {count}
          </span>
        );
        if (!latestAlertId) return inner;
        return (
          <Tooltip title="查看最新 Alert 详情">
            <Link
              to={`/monitoring/${record.id}/alert/${latestAlertId}`}
              style={{ textDecoration: "none" }}
            >
              {inner}
            </Link>
          </Tooltip>
        );
      },
    },
    {
      title: "操作",
      key: "action",
      width: 100,
      render: (_: unknown, record: MonitoringCustomer) => (
        <Tooltip title="立即扫描此客户">
          <Button
            size="small"
            icon={<SyncOutlined />}
            onClick={() => {
              void handleScanOne(record.id);
            }}
            style={{
              borderColor: TOKEN.borderColor,
              color: TOKEN.textSecondary,
              fontSize: 12,
              willChange: "transform",
            }}
          >
            扫描
          </Button>
        </Tooltip>
      ),
    },
  ];

  return (
    <div
      style={{
        padding: 24,
        backgroundColor: TOKEN.pageBg,
        minHeight: "100%",
      }}
    >
      {/* ── Page header ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 20,
        }}
      >
        <div>
          <h2
            style={{
              margin: 0,
              fontSize: 20,
              fontWeight: 600,
              color: TOKEN.textPrimary,
              letterSpacing: "-0.01em",
            }}
          >
            持仓预警
          </h2>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 13,
              color: TOKEN.textTertiary,
            }}
          >
            每 5 秒自动刷新 · 监控客户持仓异动信号
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {loading && (
            <SyncOutlined
              spin
              style={{ color: TOKEN.textTertiary, fontSize: 14 }}
            />
          )}
        </div>
      </div>

      {/* ── Stats row: 4 cards ── */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            icon={<TeamOutlined />}
            label="总客户数"
            value={stats.total}
            loading={loading}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            icon={<ThunderboltOutlined />}
            label="今日扫描次数"
            value={stats.todayScans}
            loading={loading}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            icon={<WarningOutlined />}
            label="黄色预警 (24h)"
            value={stats.yellow24h}
            valueColor={stats.yellow24h > 0 ? TOKEN.accentYellow : undefined}
            loading={loading}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            icon={<AlertOutlined />}
            label="红色告警 (24h)"
            value={stats.red24h}
            valueColor={stats.red24h > 0 ? TOKEN.accentRed : undefined}
            loading={loading}
          />
        </Col>
      </Row>

      {/* ── Toolbar ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 16,
          padding: "12px 16px",
          backgroundColor: TOKEN.cardBg,
          border: `1px solid ${TOKEN.borderColor}`,
          borderRadius: 8,
        }}
      >
        <Input.Search
          placeholder="搜索客户名 / ts_code"
          allowClear
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 220 }}
          size="middle"
        />
        <Select
          placeholder="行业"
          allowClear
          style={{ width: 140 }}
          options={industryOptions}
          onChange={(v: string | undefined) => setIndustryFilter(v)}
          size="middle"
        />
        <Select
          defaultValue="all"
          style={{ width: 110 }}
          options={[
            { value: "all", label: "全部状态" },
            { value: "enabled", label: "已启用" },
            { value: "disabled", label: "已禁用" },
          ]}
          onChange={(v: "all" | "enabled" | "disabled") => setStatusFilter(v)}
          size="middle"
        />
        <Space style={{ marginLeft: "auto" }}>
          <Button
            type="primary"
            icon={scanning ? <SyncOutlined spin /> : <ThunderboltOutlined />}
            onClick={() => {
              void handleScanAll();
            }}
            disabled={scanning || filtered.length === 0}
            style={{
              backgroundColor: TOKEN.accentRed,
              borderColor: TOKEN.accentRed,
              willChange: "transform",
              transition: "transform 0.15s, box-shadow 0.15s",
            }}
            onMouseDown={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform =
                "translateY(1px) scale(0.98)";
            }}
            onMouseUp={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform = "";
            }}
          >
            {scanning ? "扫描中..." : "立即扫描全部"}
          </Button>
        </Space>
      </div>

      {/* ── Table ── */}
      {loading && customers.length === 0 ? (
        // Loading skeleton
        <div
          style={{
            backgroundColor: TOKEN.cardBg,
            border: `1px solid ${TOKEN.borderColor}`,
            borderRadius: 8,
            padding: 24,
          }}
        >
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} active paragraph={{ rows: 1 }} />
          ))}
        </div>
      ) : filtered.length === 0 && !loading ? (
        // Empty state
        <div
          style={{
            backgroundColor: TOKEN.cardBg,
            border: `1px solid ${TOKEN.borderColor}`,
            borderRadius: 8,
            padding: 48,
            textAlign: "center",
          }}
        >
          <Empty
            description={
              <span style={{ color: TOKEN.textTertiary, fontSize: 14 }}>
                {customers.length === 0
                  ? "暂无监控客户，请前往配置页添加"
                  : "没有匹配的客户，请调整筛选条件"}
              </span>
            }
          />
        </div>
      ) : (
        <div
          style={{
            backgroundColor: TOKEN.cardBg,
            border: `1px solid ${TOKEN.borderColor}`,
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          <Table<MonitoringCustomer>
            rowKey="id"
            columns={columns}
            dataSource={filtered}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: false }}
            scroll={{ x: 900 }}
            onRow={(record) => ({
              style: {
                transition: "background 0.15s",
              },
              onMouseEnter: (e) => {
                (e.currentTarget as HTMLTableRowElement).style.backgroundColor =
                  "rgba(192,57,43,0.03)";
              },
              onMouseLeave: (e) => {
                (e.currentTarget as HTMLTableRowElement).style.backgroundColor =
                  "";
              },
              "data-customer-id": record.id,
            })}
            locale={{
              emptyText: (
                <Empty
                  description={
                    <span style={{ color: TOKEN.textTertiary }}>暂无数据</span>
                  }
                />
              ),
            }}
            style={{
              fontSize: 13,
            }}
          />
        </div>
      )}
    </div>
  );
}
