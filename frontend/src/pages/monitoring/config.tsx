import { useCallback, useEffect, useState } from "react";
import {
  Alert as AntAlert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  TimePicker,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  RedoOutlined,
  SettingOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
// NOTE: v1.0 backend retired the customers / config endpoints (Task 13).
// Customer CRUD is no longer wired to the backend on this page.
// The global config / thresholds sections below are frontend-only (no backend
// persistence) and remain as a UI stub until the backend re-exposes them.
import type { MonitoringConfig, MonitoringCustomer } from "@/types/monitoring";

// ── Customer CRUD form values ──
interface CustomerFormValues {
  ts_code: string;
  name: string;
  industry: string;
  enabled: boolean;
}

// ── Global config form values ──
interface GlobalFormValues {
  scan_time: Dayjs;
  daily_budget_cny: number;
  yellow_email: boolean;
  escalation_concurrent: number;
  recipients: string[];
}

// ── Threshold override state per rule ──
type ThresholdOverrides = Record<string, Record<string, number | null>>;

export default function MonitoringConfig() {
  // v1.0 退役客户 CRUD 端点后,这些 state 恒初始值(不再 set),仅用于渲染退役占位 UI
  const [customers] = useState<MonitoringCustomer[]>([]);
  const [config] = useState<MonitoringConfig | null>(null);
  const [pageLoading, setPageLoading] = useState(true);

  // Customer modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState<MonitoringCustomer | null>(null);
  const [modalLoading] = useState(false);
  const [customerForm] = Form.useForm<CustomerFormValues>();

  // Global config form
  const [globalForm] = Form.useForm<GlobalFormValues>();
  const [globalSaving, setGlobalSaving] = useState(false);

  // Threshold overrides (frontend-only display; backend read-only in v0.8.3)
  const [thresholdOverrides, setThresholdOverrides] = useState<ThresholdOverrides>({});

  // ── Data fetch ──
  // NOTE: v1.0 backend retired customers/config endpoints; no backend fetch here.
  // pageLoading is set false immediately; customer list and config stay as stubs.
  const refresh = useCallback(async () => {
    setPageLoading(false);
    // Customers and config start empty — that is expected in v1.0.
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Sync global form when config loads
  useEffect(() => {
    if (!config) return;
    const [hour, min] = (config.scan_time ?? "16:30").split(":").map(Number);
    globalForm.setFieldsValue({
      scan_time: dayjs().hour(hour ?? 16).minute(min ?? 30).second(0),
      daily_budget_cny: config.daily_budget_cny ?? 10,
      yellow_email: false,
      escalation_concurrent: 1,
      recipients: [],
    });
  }, [config, globalForm]);

  // ── Open modal for Add or Edit ──
  const openAdd = () => {
    setEditingCustomer(null);
    customerForm.resetFields();
    customerForm.setFieldsValue({ enabled: true });
    setModalOpen(true);
  };

  const openEdit = (c: MonitoringCustomer) => {
    setEditingCustomer(c);
    customerForm.setFieldsValue({
      ts_code: c.ts_code,
      name: c.name,
      industry: c.industry,
      enabled: c.enabled,
    });
    setModalOpen(true);
  };

  const handleModalOk = () => {
    // v1.0: customers endpoint retired — backend CRUD not available.
    // Fail loud so the user knows this is not silently succeeding.
    void window.$app.message.error(
      "客户管理接口已在 v1.0 中退役，暂不支持添加/编辑操作。请联系管理员。",
    );
    setModalOpen(false);
    customerForm.resetFields();
  };

  const handleDelete = (_id: string, name: string) => {
    // v1.0: customers endpoint retired — backend CRUD not available.
    void window.$app.message.error(
      `无法删除客户「${name}」：v1.0 客户管理接口已退役，请联系管理员。`,
    );
  };

  // ── Global config save (frontend-only display; PATCH endpoint not in v0.8.3) ──
  const handleGlobalSave = async () => {
    let vals: GlobalFormValues;
    try {
      vals = await globalForm.validateFields();
    } catch {
      return;
    }
    setGlobalSaving(true);
    // Simulate save delay — backend PATCH /api/monitoring/config not in v0.8.3 scope
    await new Promise<void>((resolve) => setTimeout(resolve, 600));
    console.info("[MonitoringConfig] global config (frontend-only):", vals);
    void window.$app.message.info("配置已保存（当前版本仅前端生效，重启后恢复默认值）");
    setGlobalSaving(false);
  };

  // ── Threshold overrides ──
  const handleThresholdChange = (rule: string, key: string, value: number | null) => {
    setThresholdOverrides((prev) => ({
      ...prev,
      [rule]: { ...(prev[rule] ?? {}), [key]: value },
    }));
  };

  const handleThresholdReset = (rule: string) => {
    setThresholdOverrides((prev) => {
      const next = { ...prev };
      delete next[rule];
      return next;
    });
    void window.$app.message.success(`${rule} 阈值已重置为默认值`);
  };

  // ── Customer table columns ──
  const customerColumns: ColumnsType<MonitoringCustomer> = [
    {
      title: "客户名",
      dataIndex: "name",
      key: "name",
      width: 130,
      render: (name: string) => (
        <Typography.Text strong style={{ fontSize: 13 }}>
          {name}
        </Typography.Text>
      ),
    },
    {
      title: "ts_code",
      dataIndex: "ts_code",
      key: "ts_code",
      width: 120,
      render: (code: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {code}
        </Typography.Text>
      ),
    },
    {
      title: "行业",
      dataIndex: "industry",
      key: "industry",
      width: 120,
      render: (industry: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          {industry}
        </Typography.Text>
      ),
    },
    {
      title: "启用",
      dataIndex: "enabled",
      key: "enabled",
      width: 70,
      align: "center",
      render: (enabled: boolean) => (
        <Switch size="small" checked={enabled} disabled style={{ cursor: "default" }} />
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 110,
      render: (_: unknown, record: MonitoringCustomer) => (
        <Space size={4}>
          <Tooltip title="编辑">
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => openEdit(record)}
            />
          </Tooltip>
          <Tooltip title="删除">
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => { void handleDelete(record.id, record.name); }}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  // ── Threshold tabs ──
  const thresholds = config?.thresholds ?? {};
  const thresholdTabItems = Object.keys(thresholds).map((rule) => {
    const defaults = thresholds[rule];
    const overrides = thresholdOverrides[rule] ?? {};
    const hasOverrides = Object.keys(overrides).length > 0;
    return {
      key: rule,
      label: (
        <Space size={4}>
          <span style={{ fontSize: 13 }}>{rule}</span>
          {hasOverrides && <Tag color="warning" style={{ fontSize: 11, margin: 0 }}>已覆盖</Tag>}
        </Space>
      ),
      children: (
        <div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
            <Button
              size="small"
              icon={<RedoOutlined />}
              onClick={() => handleThresholdReset(rule)}
            >
              重置为默认值
            </Button>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
              gap: "12px 24px",
            }}
          >
            {Object.entries(defaults).map(([k, defaultVal]) => {
              const overrideVal = overrides[k];
              const displayVal = overrideVal ?? defaultVal;
              const isOverridden = overrideVal !== undefined && overrideVal !== null;
              return (
                <div key={k}>
                  <div style={{ marginBottom: 4 }}>
                    <Typography.Text
                      type={isOverridden ? "warning" : "secondary"}
                      style={{ fontSize: 12 }}
                    >
                      {k}
                    </Typography.Text>
                    {isOverridden && (
                      <Tag color="warning" style={{ marginLeft: 6, fontSize: 10 }}>
                        已覆盖
                      </Tag>
                    )}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <InputNumber
                      size="small"
                      value={displayVal}
                      style={{ width: 120, fontSize: 12 }}
                      onChange={(v) => handleThresholdChange(rule, k, v)}
                      placeholder={String(defaultVal)}
                    />
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      默认: {defaultVal}
                    </Typography.Text>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ),
    };
  });

  return (
    <div style={{ padding: 16 }}>
      {/* ── Page header ── */}
      <div style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          监控配置
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          扫描参数和信号阈值（前端配置，重启后恢复默认值）
        </Typography.Text>
      </div>

      {/* ── v1.0 migration notice ── */}
      <AntAlert
        type="warning"
        showIcon
        message="客户管理功能正在重构"
        description="v1.0 已退役客户 CRUD 接口，监控标的改由「持仓」页管理。全局配置与阈值调整仅前端生效，后端接口将在后续版本补全。"
        style={{ marginBottom: 16 }}
      />

      {pageLoading ? (
        <Card>
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} active paragraph={{ rows: 2 }} style={{ marginBottom: 16 }} />
          ))}
        </Card>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* ── Section 1: Customer list CRUD ── */}
          <Card
            title={
              <Space>
                <TeamOutlined />
                <span>客户列表</span>
                <Typography.Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                  共 {customers.length.toString()} 位客户
                </Typography.Text>
              </Space>
            }
            extra={
              <Button
                type="primary"
                size="small"
                icon={<PlusOutlined />}
                onClick={openAdd}
              >
                添加客户
              </Button>
            }
            size="small"
          >
            <Table<MonitoringCustomer>
              rowKey="id"
              columns={customerColumns}
              dataSource={customers}
              size="small"
              pagination={customers.length > 15 ? { pageSize: 15, showSizeChanger: false } : false}
              scroll={{ x: 560 }}
              locale={{
                emptyText: (
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    暂无监控客户，点击「添加客户」开始配置
                  </Typography.Text>
                ),
              }}
            />
          </Card>

          {/* ── Section 2: Global config ── */}
          <Card
            title={
              <Space>
                <SettingOutlined />
                <span>全局配置</span>
              </Space>
            }
            size="small"
          >
            <Typography.Text type="secondary" style={{ fontSize: 13, display: "block", marginBottom: 16 }}>
              扫描调度与成本控制参数
            </Typography.Text>
            <Form<GlobalFormValues>
              form={globalForm}
              layout="vertical"
              style={{ maxWidth: 640 }}
            >
              {/* Row 1: scan time + daily budget */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                  gap: "0 24px",
                }}
              >
                <Form.Item
                  label="每日扫描时间"
                  name="scan_time"
                  rules={[{ required: true, message: "请选择扫描时间" }]}
                  style={{ marginBottom: 14 }}
                >
                  <TimePicker
                    format="HH:mm"
                    style={{ width: "100%" }}
                    placeholder="16:30"
                    allowClear={false}
                  />
                </Form.Item>

                <Form.Item
                  label="每日 Cost Cap (CNY)"
                  name="daily_budget_cny"
                  rules={[{ required: true, message: "请填写每日预算" }]}
                  style={{ marginBottom: 14 }}
                >
                  <InputNumber
                    min={1}
                    max={1000}
                    step={1}
                    precision={0}
                    prefix="¥"
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </div>

              {/* Row 2: switches + escalation */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                  gap: "0 24px",
                }}
              >
                <Form.Item
                  label="黄色预警发邮件"
                  name="yellow_email"
                  valuePropName="checked"
                  style={{ marginBottom: 14 }}
                >
                  <Switch size="small" />
                </Form.Item>

                <Form.Item
                  label="Escalation 最大并发"
                  name="escalation_concurrent"
                  rules={[{ required: true, message: "请设置并发上限" }]}
                  style={{ marginBottom: 14 }}
                >
                  <InputNumber min={1} max={5} precision={0} style={{ width: "100%" }} />
                </Form.Item>
              </div>

              {/* Row 3: email recipients */}
              <Form.Item
                label="邮件接收人"
                name="recipients"
                style={{ marginBottom: 16 }}
                extra="输入邮箱地址后按 Enter 添加，支持多人"
              >
                <Select
                  mode="tags"
                  placeholder="输入邮箱地址后按 Enter"
                  style={{ width: "100%" }}
                  tokenSeparators={[",", " "]}
                  open={false}
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  type="primary"
                  onClick={() => { void handleGlobalSave(); }}
                  loading={globalSaving}
                >
                  保存配置
                </Button>
              </Form.Item>
            </Form>
          </Card>

          {/* ── Section 3: Signal threshold config ── */}
          <Card
            title={
              <Space>
                <SettingOutlined />
                <span>信号阈值配置</span>
              </Space>
            }
            size="small"
          >
            <Typography.Text type="secondary" style={{ fontSize: 13, display: "block", marginBottom: 16 }}>
              各 Rule 的触发阈值，修改后仅前端生效（v0.8.3 backend read-only）
            </Typography.Text>
            {Object.keys(thresholds).length === 0 ? (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                暂无阈值配置数据
              </Typography.Text>
            ) : (
              <Tabs items={thresholdTabItems} size="small" />
            )}
          </Card>
        </div>
      )}

      {/* ── Add / Edit Customer Modal ── */}
      <Modal
        open={modalOpen}
        title={editingCustomer ? "编辑客户" : "添加客户"}
        width={480}
        onCancel={() => {
          setModalOpen(false);
          customerForm.resetFields();
        }}
        onOk={() => { void handleModalOk(); }}
        okText={editingCustomer ? "保存" : "添加"}
        cancelText="取消"
        confirmLoading={modalLoading}
        destroyOnHidden
      >
        <Form<CustomerFormValues>
          form={customerForm}
          layout="vertical"
          initialValues={{ enabled: true }}
        >
          <Form.Item
            name="ts_code"
            label="股票代码"
            rules={[
              { required: true, message: "请输入股票代码" },
              {
                pattern: /^\d{6}\.(SH|SZ|BJ)$/,
                message: "格式：600519.SH / 000001.SZ / 430047.BJ",
              },
            ]}
            style={{ marginBottom: 14 }}
          >
            <Input
              placeholder="600519.SH"
              disabled={!!editingCustomer}
            />
          </Form.Item>

          <Form.Item
            name="name"
            label="客户名 / 股票简称"
            rules={[{ required: true, message: "请输入客户名" }]}
            style={{ marginBottom: 14 }}
          >
            <Input placeholder="贵州茅台" />
          </Form.Item>

          <Form.Item
            name="industry"
            label="行业"
            rules={[{ required: true, message: "请输入行业" }]}
            style={{ marginBottom: 14 }}
          >
            <Input placeholder="食品饮料" />
          </Form.Item>

          <Form.Item
            name="enabled"
            label="启用监控"
            valuePropName="checked"
            style={{ marginBottom: 0 }}
          >
            <Switch size="small" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
