import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Collapse,
  List,
  Skeleton,
  Tag,
  Tooltip,
} from "antd";
import {
  ArrowLeftOutlined,
  SyncOutlined,
  CheckOutlined,
  LinkOutlined,
  AlertOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  RightOutlined,
} from "@ant-design/icons";
import Markdown from "@/components/markdown";
import { getAlert } from "@/api/monitoring";

// ── Design tokens — identical to index.tsx (v0.8.3-pre) ──
const TOKEN = {
  pageBg: "#faf9f7",
  cardBg: "#ffffff",
  borderColor: "#e8e4dc",
  textPrimary: "#1a1d21",
  textSecondary: "#5d6875",
  textTertiary: "#8a96a3",
  accentRed: "#c0392b",
  accentYellow: "#b8860b",
  accentGreen: "#27875a",
  monoFont: '"SF Mono", "JetBrains Mono", Consolas, monospace',
};

// ── Level config ──
type AlertLevel = "green" | "yellow" | "red";

interface LevelConfig {
  label: string;
  icon: React.ReactNode;
  textColor: string;
  bannerBg: string;
  bannerBorder: string;
  tagColor: string;
}

const LEVEL_CONFIG: Record<AlertLevel, LevelConfig> = {
  green: {
    label: "正常",
    icon: <CheckCircleOutlined />,
    textColor: TOKEN.accentGreen,
    bannerBg: "#f0faf5",
    bannerBorder: "#b7dfcc",
    tagColor: "success",
  },
  yellow: {
    label: "预警",
    icon: <WarningOutlined />,
    textColor: TOKEN.accentYellow,
    bannerBg: "#fffbf0",
    bannerBorder: "#e8d5a0",
    tagColor: "warning",
  },
  red: {
    label: "告警",
    icon: <AlertOutlined />,
    textColor: TOKEN.accentRed,
    // Desaturated warm red — not glaring
    bannerBg: "#fdf4f3",
    bannerBorder: "#e8c4c0",
    tagColor: "error",
  },
};

// ── Types for alert detail response ──
interface TriggeredSignal {
  rule_name: string;
  detected_value: unknown;
  threshold: unknown;
  explanation: string;
}

interface AlertDetailData {
  id: string;
  alert_level: string;
  report_markdown: string;
  deep_dive_text: string | null;
  escalation_status: string | null;
  report_json: {
    customer_name?: string;
    generated_at?: string;
    triggered_signals?: TriggeredSignal[];
    [key: string]: unknown;
  };
}

// ── Section wrapper ──
function Section({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        backgroundColor: TOKEN.cardBg,
        border: `1px solid ${TOKEN.borderColor}`,
        borderRadius: 8,
        overflow: "hidden",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ── Section header ──
function SectionHeader({ title }: { title: string }) {
  return (
    <div
      style={{
        padding: "12px 20px",
        borderBottom: `1px solid ${TOKEN.borderColor}`,
        fontSize: 13,
        fontWeight: 600,
        color: TOKEN.textSecondary,
        letterSpacing: "0.03em",
        backgroundColor: "#f7f5f1",
      }}
    >
      {title}
    </div>
  );
}

// ── Signal card ──
function SignalCard({ signal }: { signal: TriggeredSignal }) {
  return (
    <List.Item
      style={{
        padding: "16px 20px",
        transition: "background 0.15s cubic-bezier(0.16,1,0.3,1)",
        cursor: "default",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLLIElement).style.backgroundColor =
          "rgba(192,57,43,0.025)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLLIElement).style.backgroundColor = "";
      }}
    >
      <div style={{ width: "100%" }}>
        {/* Rule name + values row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
            marginBottom: 6,
          }}
        >
          <Tag
            style={{
              fontFamily: TOKEN.monoFont,
              fontSize: 12,
              letterSpacing: "0.02em",
              borderColor: TOKEN.borderColor,
              color: TOKEN.textPrimary,
              backgroundColor: "#f5f2ec",
              borderRadius: 4,
              padding: "1px 8px",
              margin: 0,
            }}
          >
            {signal.rule_name}
          </Tag>
          <span
            style={{
              fontSize: 12,
              color: TOKEN.textTertiary,
              fontFamily: TOKEN.monoFont,
            }}
          >
            检测值{" "}
            <span
              style={{
                color: TOKEN.accentRed,
                fontWeight: 600,
              }}
            >
              {String(signal.detected_value)}
            </span>
            {" / 阈值 "}
            <span style={{ color: TOKEN.textSecondary }}>
              {String(signal.threshold)}
            </span>
          </span>
        </div>
        {/* Explanation */}
        <p
          style={{
            margin: 0,
            fontSize: 13,
            color: TOKEN.textSecondary,
            lineHeight: 1.6,
          }}
        >
          {signal.explanation}
        </p>
      </div>
    </List.Item>
  );
}

// ── Loading skeleton ──
function DetailSkeleton() {
  return (
    <div style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
      {/* Banner skeleton */}
      <Skeleton.Input
        active
        block
        style={{ height: 80, borderRadius: 8, marginBottom: 16 }}
      />
      {/* Signals skeleton */}
      <Skeleton active paragraph={{ rows: 4 }} style={{ marginBottom: 16 }} />
      {/* Report skeleton */}
      <Skeleton active paragraph={{ rows: 8 }} />
    </div>
  );
}

// ── Main component ──
export default function AlertDetail() {
  const { aid } = useParams<{ cid: string; aid: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<AlertDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [copying, setCopying] = useState(false);

  useEffect(() => {
    if (!aid) return;
    setLoading(true);
    getAlert(aid)
      .then((res) => {
        setData(res as AlertDetailData);
      })
      .catch((e: unknown) => {
        setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [aid]);

  const handleCopyLink = async () => {
    setCopying(true);
    try {
      await navigator.clipboard.writeText(window.location.href);
      void window.$app.message.success("链接已复制");
    } catch {
      void window.$app.message.error("复制失败，请手动复制地址栏链接");
    } finally {
      setCopying(false);
    }
  };

  const handleRescan = () => {
    void window.$app.message.info("请返回列表页触发重新扫描");
  };

  const handleMarkRead = () => {
    void window.$app.message.success("已标记为已读");
  };

  // ── Loading state ──
  if (loading) return <DetailSkeleton />;

  // ── Error state ──
  if (err) {
    return (
      <div style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
        <Alert
          type="error"
          showIcon
          message="加载失败"
          description={err}
          action={
            <Button
              size="small"
              onClick={() => {
                navigate(-1);
              }}
            >
              返回
            </Button>
          }
        />
      </div>
    );
  }

  // ── Not found state ──
  if (!data) {
    return (
      <div style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
        <Alert type="warning" showIcon message="未找到该 Alert 记录" />
      </div>
    );
  }

  const rawLevel = data.alert_level as AlertLevel;
  const level: AlertLevel = ["green", "yellow", "red"].includes(rawLevel)
    ? rawLevel
    : "green";
  const levelCfg = LEVEL_CONFIG[level];
  const customerName =
    typeof data.report_json.customer_name === "string"
      ? data.report_json.customer_name
      : "未知客户";
  const generatedAt =
    typeof data.report_json.generated_at === "string"
      ? data.report_json.generated_at
      : "";
  const triggeredSignals: TriggeredSignal[] = Array.isArray(
    data.report_json.triggered_signals,
  )
    ? (data.report_json.triggered_signals as TriggeredSignal[])
    : [];

  const formattedTime = generatedAt
    ? new Date(generatedAt).toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

  return (
    <div
      style={{
        padding: "20px 24px",
        backgroundColor: TOKEN.pageBg,
        minHeight: "100%",
      }}
    >
      {/* ── Content wrapper: max-width 900px centered ── */}
      <div style={{ maxWidth: 900, margin: "0 auto" }}>
        {/* ── Back nav ── */}
        <div style={{ marginBottom: 16 }}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => {
              navigate(-1);
            }}
            style={{
              color: TOKEN.textTertiary,
              fontSize: 13,
              padding: "0 4px",
              transition: "color 0.15s",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color =
                TOKEN.textPrimary;
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color =
                TOKEN.textTertiary;
            }}
          >
            返回监控列表
          </Button>
        </div>

        {/* ────────────────────────────────────────────────── */}
        {/* Step 1: Status Banner                             */}
        {/* ────────────────────────────────────────────────── */}
        <div
          style={{
            backgroundColor: levelCfg.bannerBg,
            border: `1px solid ${levelCfg.bannerBorder}`,
            borderRadius: 8,
            padding: "20px 24px",
            marginBottom: 16,
            // Left accent stripe
            borderLeft: `4px solid ${levelCfg.textColor}`,
          }}
        >
          {/* Top row: customer name + level tag */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 8,
              marginBottom: 10,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span
                style={{
                  fontSize: levelCfg.icon ? 16 : 0,
                  color: levelCfg.textColor,
                }}
              >
                {levelCfg.icon}
              </span>
              <h1
                style={{
                  margin: 0,
                  fontSize: 18,
                  fontWeight: 700,
                  color: TOKEN.textPrimary,
                  letterSpacing: "-0.01em",
                }}
              >
                {customerName}
              </h1>
              <Tag
                color={levelCfg.tagColor}
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  borderRadius: 4,
                  letterSpacing: "0.02em",
                }}
              >
                {levelCfg.label}
              </Tag>
            </div>

            {/* Escalation badge */}
            {data.escalation_status && (
              <Tag
                icon={<RightOutlined />}
                style={{
                  borderColor: TOKEN.accentRed,
                  color: TOKEN.accentRed,
                  backgroundColor: "transparent",
                  fontSize: 12,
                  borderRadius: 4,
                }}
              >
                {data.escalation_status === "escalated"
                  ? "已升级处理"
                  : data.escalation_status}
              </Tag>
            )}
          </div>

          {/* Bottom row: meta info */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontSize: 12,
                color: TOKEN.textTertiary,
                fontFamily: TOKEN.monoFont,
                letterSpacing: "0.02em",
              }}
            >
              生成于 {formattedTime}
            </span>
            <span
              style={{
                fontSize: 12,
                color: TOKEN.textTertiary,
                fontFamily: TOKEN.monoFont,
              }}
            >
              ID: {data.id.slice(0, 8)}…
            </span>
            {triggeredSignals.length > 0 && (
              <span
                style={{
                  fontSize: 12,
                  color: levelCfg.textColor,
                  fontWeight: 500,
                }}
              >
                {triggeredSignals.length} 个触发信号
              </span>
            )}
          </div>
        </div>

        {/* ────────────────────────────────────────────────── */}
        {/* Step 2: Triggered signals list                    */}
        {/* ────────────────────────────────────────────────── */}
        <Section style={{ marginBottom: 16 }}>
          <SectionHeader title={`触发信号 (${triggeredSignals.length.toString()})`} />
          {triggeredSignals.length === 0 ? (
            <div
              style={{
                padding: "32px 20px",
                textAlign: "center",
                color: TOKEN.textTertiary,
                fontSize: 13,
              }}
            >
              无触发信号 — 当前持仓状态正常
            </div>
          ) : (
            <List
              dataSource={triggeredSignals}
              renderItem={(signal, idx) => (
                <div
                  key={idx}
                  style={{
                    borderBottom:
                      idx < triggeredSignals.length - 1
                        ? `1px solid ${TOKEN.borderColor}`
                        : "none",
                  }}
                >
                  <SignalCard signal={signal} />
                </div>
              )}
              split={false}
              style={{ padding: 0 }}
            />
          )}
        </Section>

        {/* ────────────────────────────────────────────────── */}
        {/* Step 3: Report markdown                           */}
        {/* ────────────────────────────────────────────────── */}
        <Section style={{ marginBottom: 16 }}>
          <SectionHeader title="分析报告" />
          <div
            style={{
              padding: "20px 24px",
              fontSize: 14,
              lineHeight: 1.75,
              color: TOKEN.textPrimary,
            }}
          >
            {data.report_markdown ? (
              <Markdown
                value={data.report_markdown}
                className="alert-report-markdown"
              />
            ) : (
              <span style={{ color: TOKEN.textTertiary }}>暂无报告内容</span>
            )}
          </div>
        </Section>

        {/* ────────────────────────────────────────────────── */}
        {/* Step 4: Deep dive collapse (red only)             */}
        {/* ────────────────────────────────────────────────── */}
        {level === "red" && data.deep_dive_text && (
          <div style={{ marginBottom: 16 }}>
            <Collapse
              defaultActiveKey={["deep_dive"]}
              expandIconPosition="end"
              style={{
                backgroundColor: TOKEN.cardBg,
                border: `1px solid ${TOKEN.borderColor}`,
                borderRadius: 8,
                // Hollow "depth" shadow — indicates elevated, important content
                boxShadow: `0 0 0 3px rgba(192,57,43,0.06), 0 2px 8px rgba(192,57,43,0.04)`,
              }}
              items={[
                {
                  key: "deep_dive",
                  label: (
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        fontSize: 13,
                        fontWeight: 600,
                        color: TOKEN.accentRed,
                        letterSpacing: "0.02em",
                      }}
                    >
                      <AlertOutlined />
                      深度调查 (Escalation 输出)
                    </div>
                  ),
                  children: (
                    <div
                      style={{
                        padding: "4px 4px 8px",
                        fontSize: 14,
                        lineHeight: 1.75,
                        color: TOKEN.textPrimary,
                        borderTop: `1px solid ${TOKEN.borderColor}`,
                        paddingTop: 16,
                      }}
                    >
                      <Markdown value={data.deep_dive_text} />
                    </div>
                  ),
                  style: {
                    border: "none",
                  },
                },
              ]}
            />
          </div>
        )}

        {/* ────────────────────────────────────────────────── */}
        {/* Step 5: Action buttons                            */}
        {/* ────────────────────────────────────────────────── */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            padding: "16px 0 8px",
            borderTop: `1px solid ${TOKEN.borderColor}`,
          }}
        >
          {/* Primary: re-scan */}
          <Button
            type="primary"
            icon={<SyncOutlined />}
            onClick={handleRescan}
            style={{
              backgroundColor: TOKEN.accentRed,
              borderColor: TOKEN.accentRed,
              willChange: "transform",
              transition: "transform 0.12s cubic-bezier(0.16,1,0.3,1), box-shadow 0.12s",
            }}
            onMouseDown={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform =
                "translateY(1px) scale(0.98)";
            }}
            onMouseUp={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform = "";
            }}
          >
            再次扫描
          </Button>

          {/* Secondary: mark read */}
          <Button
            icon={<CheckOutlined />}
            onClick={handleMarkRead}
            style={{
              borderColor: TOKEN.borderColor,
              color: TOKEN.textSecondary,
              willChange: "transform",
              transition: "transform 0.12s cubic-bezier(0.16,1,0.3,1)",
            }}
            onMouseDown={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform =
                "translateY(1px) scale(0.98)";
            }}
            onMouseUp={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform = "";
            }}
          >
            标记已读
          </Button>

          {/* Ghost: copy link */}
          <Tooltip title="复制当前页面链接">
            <Button
              type="text"
              icon={<LinkOutlined />}
              loading={copying}
              onClick={() => {
                void handleCopyLink();
              }}
              style={{
                color: TOKEN.textTertiary,
                fontSize: 13,
              }}
            >
              复制分享链接
            </Button>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
