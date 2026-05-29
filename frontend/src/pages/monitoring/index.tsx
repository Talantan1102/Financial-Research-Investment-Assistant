import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Badge,
  Button,
  Col,
  Empty,
  Input,
  Row,
  Skeleton,
  Space,
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
  listSignals,
  triggerRefresh,
  type SignalSummary,
} from "@/api/monitoring";
import type { AlertLevel } from "@/types/monitoring";

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
  const [signals, setSignals] = useState<SignalSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [search, setSearch] = useState("");

  const refresh = useCallback(async () => {
    try {
      const s = await listSignals(50);
      setSignals(s);
    } catch (err) {
      console.error("[MonitoringIndex] refresh error:", err);
      void window.$app.message.error("加载监控信号失败，请检查登录状态或稍后重试");
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

  // ── Derived stats from signals ──
  const stats = useMemo(() => {
    const since24h = Date.now() - 24 * 3600 * 1000;
    const recent = signals.filter(
      (s) => s.created_at && new Date(s.created_at).getTime() > since24h,
    );
    const distinctTsCodes = new Set(signals.map((s) => s.ts_code));
    return {
      total: distinctTsCodes.size,
      todayScans: signals.length,
      yellow24h: recent.filter((s) => s.alert_level === "yellow").length,
      red24h: recent.filter((s) => s.alert_level === "red").length,
    };
  }, [signals]);

  // ── Filtered signals list ──
  const filtered = useMemo(() => {
    return signals.filter(
      (s) =>
        !search ||
        s.ts_code.toLowerCase().includes(search.toLowerCase()) ||
        s.detail_status.toLowerCase().includes(search.toLowerCase()),
    );
  }, [signals, search]);

  // ── Trigger detection cycle for current user ──
  const handleScanAll = async () => {
    setScanning(true);
    try {
      const { status } = await triggerRefresh();
      void window.$app.message.success(`检测周期已入队 (${status})`);
      // Optimistic: refresh after brief delay
      setTimeout(() => {
        void refresh();
      }, 1500);
    } catch (err) {
      console.error("[MonitoringIndex] triggerRefresh error:", err);
      void window.$app.message.error("触发扫描失败，请重试");
    } finally {
      setScanning(false);
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

  // ── Table columns (v1.0: signal-centric) ──
  const columns: ColumnsType<SignalSummary> = [
    {
      title: "标的代码",
      dataIndex: "ts_code",
      key: "ts_code",
      width: 130,
      render: (code: string, record: SignalSummary) => (
        <Link
          to={`/monitoring/${record.id}/alert/${record.id}`}
          style={{
            color: TOKEN.textPrimary,
            fontWeight: 500,
            fontFamily: TOKEN.monoFont,
            fontSize: 13,
            letterSpacing: "0.04em",
            transition: "color 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.color = TOKEN.accentRed;
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.color = TOKEN.textPrimary;
          }}
        >
          {code}
        </Link>
      ),
    },
    {
      title: "预警等级",
      dataIndex: "alert_level",
      key: "alert_level",
      width: 100,
      render: (level: AlertLevel) => <AlertDot level={level} />,
    },
    {
      title: "详情状态",
      dataIndex: "detail_status",
      key: "detail_status",
      width: 120,
      render: (status: string) => (
        <Tag
          style={{
            borderColor: TOKEN.borderColor,
            color: TOKEN.textSecondary,
            backgroundColor: "#f5f2ec",
            fontSize: 12,
            borderRadius: 4,
          }}
        >
          {status}
        </Tag>
      ),
    },
    {
      title: "生成时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 140,
      render: (ts: string | null) => (
        <span
          style={{
            fontFamily: TOKEN.monoFont,
            fontSize: 12,
            color: TOKEN.textTertiary,
          }}
        >
          {formatTime(ts ?? undefined)}
        </span>
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 100,
      render: (_: unknown, record: SignalSummary) => (
        <Tooltip title="查看 Alert 详情">
          <Link
            to={`/monitoring/${record.id}/alert/${record.id}`}
            style={{
              fontSize: 12,
              color: TOKEN.textSecondary,
              border: `1px solid ${TOKEN.borderColor}`,
              borderRadius: 4,
              padding: "2px 8px",
              textDecoration: "none",
              transition: "color 0.15s",
            }}
          >
            详情
          </Link>
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
            label="监控标的数"
            value={stats.total}
            loading={loading}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            icon={<ThunderboltOutlined />}
            label="信号总数"
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
          placeholder="搜索标的代码 / 详情状态"
          allowClear
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 240 }}
          size="middle"
        />
        <Space style={{ marginLeft: "auto" }}>
          <Button
            type="primary"
            icon={scanning ? <SyncOutlined spin /> : <ThunderboltOutlined />}
            onClick={() => {
              void handleScanAll();
            }}
            disabled={scanning}
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
      {loading && signals.length === 0 ? (
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
        // Empty state — neutral wording; no dead link to /config
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
                {signals.length === 0
                  ? "暂无监控信号数据，点击「立即扫描全部」触发检测周期"
                  : "没有匹配的信号，请调整搜索条件"}
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
          <Table<SignalSummary>
            rowKey="id"
            columns={columns}
            dataSource={filtered}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: false }}
            scroll={{ x: 600 }}
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
              "data-signal-id": record.id,
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
