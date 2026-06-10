"""Phase 2 metric implementations.

去推荐改造(2026-06-04)后 4 metric 对应 spec § 4.2(预测回测原 M4 已下线):
  M1 CitationMetric         — extraction
  M2 NumericalMetric        — extraction
  M3 RiskPairingMetric      — summarization (LLM judge)
  M5 CompositeJudgeMetric   — reasoning (multi-LLM consensus)
"""
