import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  List,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  ArrowLeftOutlined,
  SyncOutlined,
  CheckOutlined,
  LinkOutlined,
  AlertOutlined,
  WarningOutlined,
  CheckCircleOutlined,
} from "@ant-design/icons";
import Markdown from "@/components/markdown";
import { getAlert } from "@/api/monitoring";

// ── Level config — antd semantic colors only ──
type AlertLevel = "green" | "yellow" | "red";

interface LevelConfig {
  label: string;
  icon: React.ReactNode;
  tagColor: string;
  alertType: "success" | "warning" | "error";
}

const LEVEL_CONFIG: Record<AlertLevel, LevelConfig> = {
  green: {
    label: "正常",
    icon: <CheckCircleOutlined />,
    tagColor: "success",
    alertType: "success",
  },
  yellow: {
    label: "预警",
    icon: <WarningOutlined />,
    tagColor: "warning",
    alertType: "warning",
  },
  red: {
    label: "告警",
    icon: <AlertOutlined />,
    tagColor: "error",
    alertType: "error",
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

// ── Signal card ──
function SignalCard({ signal }: { signal: TriggeredSignal }) {
  return (
    <List.Item>
      <div style={{ width: "100%" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
            marginBottom: 6,
          }}
        >
          <Tag>{signal.rule_name}</Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            检测值{" "}
            <Typography.Text type="danger" strong style={{ fontSize: 12 }}>
              {String(signal.detected_value)}
            </Typography.Text>
            {" / 阈值 "}
            {String(signal.threshold)}
          </Typography.Text>
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          {signal.explanation}
        </Typography.Text>
      </div>
    </List.Item>
  );
}

// ── Loading skeleton ──
function DetailSkeleton() {
  return (
    <div style={{ padding: 16, maxWidth: 900, margin: "0 auto" }}>
      <Skeleton.Input active block style={{ height: 80, borderRadius: 8, marginBottom: 16 }} />
      <Skeleton active paragraph={{ rows: 4 }} style={{ marginBottom: 16 }} />
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

  if (loading) return <DetailSkeleton />;

  if (err) {
    return (
      <div style={{ padding: 16, maxWidth: 900, margin: "0 auto" }}>
        <Alert
          type="error"
          showIcon
          message="加载失败"
          description={err}
          action={
            <Button size="small" onClick={() => { navigate(-1); }}>
              返回
            </Button>
          }
        />
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ padding: 16, maxWidth: 900, margin: "0 auto" }}>
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
    <div style={{ padding: 16 }}>
      <div style={{ maxWidth: 900, margin: "0 auto" }}>
        {/* ── Back nav ── */}
        <div style={{ marginBottom: 16 }}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => { navigate(-1); }}
          >
            返回监控列表
          </Button>
        </div>

        {/* ── Status banner ── */}
        <Alert
          type={levelCfg.alertType}
          showIcon
          icon={levelCfg.icon}
          style={{ marginBottom: 16 }}
          message={
            <Space size={8}>
              <Typography.Text strong style={{ fontSize: 16 }}>
                {customerName}
              </Typography.Text>
              <Tag color={levelCfg.tagColor}>{levelCfg.label}</Tag>
              {data.escalation_status && (
                <Tag color="error">
                  {data.escalation_status === "escalated"
                    ? "已升级处理"
                    : data.escalation_status}
                </Tag>
              )}
            </Space>
          }
          description={
            <Descriptions size="small" column={{ xs: 1, sm: 3 }} style={{ marginTop: 8 }}>
              <Descriptions.Item label="生成时间">{formattedTime}</Descriptions.Item>
              <Descriptions.Item label="ID">
                {data.id.slice(0, 8)}…
              </Descriptions.Item>
              {triggeredSignals.length > 0 && (
                <Descriptions.Item label="触发信号数">
                  <Tag color={levelCfg.tagColor}>{triggeredSignals.length} 个</Tag>
                </Descriptions.Item>
              )}
            </Descriptions>
          }
        />

        {/* ── Triggered signals ── */}
        <Card
          title={`触发信号 (${triggeredSignals.length.toString()})`}
          size="small"
          style={{ marginBottom: 16 }}
        >
          {triggeredSignals.length === 0 ? (
            <Typography.Text type="secondary">
              无触发信号 — 当前持仓状态正常
            </Typography.Text>
          ) : (
            <List
              dataSource={triggeredSignals}
              renderItem={(signal) => <SignalCard signal={signal} />}
              size="small"
            />
          )}
        </Card>

        {/* ── Report markdown ── */}
        <Card title="分析报告" size="small" style={{ marginBottom: 16 }}>
          {data.report_markdown ? (
            <Markdown
              value={data.report_markdown}
              className="alert-report-markdown"
            />
          ) : (
            <Typography.Text type="secondary">暂无报告内容</Typography.Text>
          )}
        </Card>

        {/* ── Deep dive collapse (red only) ── */}
        {level === "red" && data.deep_dive_text && (
          <Card style={{ marginBottom: 16 }} bodyStyle={{ padding: 0 }}>
            <Collapse
              defaultActiveKey={["deep_dive"]}
              expandIconPosition="end"
              ghost
              items={[
                {
                  key: "deep_dive",
                  label: (
                    <Space>
                      <AlertOutlined />
                      <Typography.Text strong>深度调查 (Escalation 输出)</Typography.Text>
                    </Space>
                  ),
                  children: (
                    <div style={{ padding: "0 16px 16px" }}>
                      <Markdown value={data.deep_dive_text} />
                    </div>
                  ),
                },
              ]}
            />
          </Card>
        )}

        {/* ── Action buttons ── */}
        <div style={{ borderTop: "1px solid rgba(0,0,0,0.06)", paddingTop: 16 }}>
          <Space wrap>
            <Button type="primary" icon={<SyncOutlined />} onClick={handleRescan}>
              再次扫描
            </Button>
            <Button icon={<CheckOutlined />} onClick={handleMarkRead}>
              标记已读
            </Button>
            <Tooltip title="复制当前页面链接">
              <Button
                type="text"
                icon={<LinkOutlined />}
                loading={copying}
                onClick={() => { void handleCopyLink(); }}
              >
                复制分享链接
              </Button>
            </Tooltip>
          </Space>
        </div>
      </div>
    </div>
  );
}
