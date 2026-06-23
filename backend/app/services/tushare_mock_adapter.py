"""Adapter wrapping legacy MockTushareService into TushareService Protocol shape.

Lazy import to avoid app/service/__init__.py legacy import chain at module load.
The inner MockTushareService instance is built on first method call (lazy), so
constructing LegacyMockTushareAdapter does NOT instantiate LLMService. This
allows unit tests (LLM_MODE=none guard) to call build_tushare_service() and do
isinstance checks without triggering the LLM_MODE=none RuntimeError.

Notes:
- MockTushareService.__init__ requires an LLMService instance; we build one
  via build_llm_service_from_env() on first use.
- aclose() is a no-op: legacy MockTushareService holds no network connections
  or file handles that require explicit cleanup.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import pandas as pd


class LegacyMockTushareAdapter:
    """Wraps legacy MockTushareService to satisfy TushareService Protocol.

    Delegates each Protocol method to the corresponding generate_* method
    on the inner legacy mock instance. The inner instance is created lazily
    on first method call to avoid LLMService construction at build time.
    """

    def __init__(self) -> None:
        self._inner: Any = None  # lazy; built on first use via _ensure_inner()

    def _ensure_inner(self) -> Any:
        """Build MockTushareService on first call (lazy initialization)."""
        if self._inner is not None:
            return self._inner

        # Build LLMService — MockTushareService.__init__ requires it.
        from app.services.openai_client import build_llm_service_from_env

        llm = build_llm_service_from_env()

        # Load legacy module directly to avoid app/service/__init__.py chain.
        path = Path(__file__).resolve().parents[1] / "service" / "mock_tushare_service.py"
        spec = spec_from_file_location("_mock_tushare_module", str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        self._inner = module.MockTushareService(llm=llm)
        return self._inner

    async def get_daily(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        return await self._ensure_inner().generate_daily_data(
            ts_code=ts_code, start_date=start, end_date=end
        )

    async def get_income(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        return await self._ensure_inner().generate_income(ts_code=ts_code)

    async def get_fina_indicator(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        return await self._ensure_inner().generate_fina_indicator(ts_code=ts_code)

    async def get_balance_sheet(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        # Deterministic inline builder — avoids the LLM-based legacy generate_balance_sheet.
        # Columns include debt_to_assets required by Task 8 FinancialRatioRule.
        # v0.8.5: extended with total_cur_assets / total_cur_liab for liquidity ratio analysis.
        #
        # Mock column contract (intentionally minimal):
        # 提供:ts_code / end_date / total_assets / total_liab / total_cur_assets /
        #       total_cur_liab / debt_to_assets — 覆盖 Task 1/8 当前规则需求.
        # 不提供:Tushare balancesheet 真实接口约 150 列(money_funds / accounts_receiv /
        #       inventories / fix_assets / lt_borr / oth_eqt_tools_p_shr / ...).
        # 未来如果需要其他列, 直接扩 fixture 行的 dict, 不要 fallback 到 LLM-based
        # generate_balance_sheet — 那条路径不 deterministic.
        rows = [
            {
                "ts_code": ts_code,
                "end_date": ed,
                "total_assets": 1.5e10 + i * 1e8,
                "total_liab": 6e9 + i * 5e7,
                "total_cur_assets": 8e9 + i * 6e7,
                "total_cur_liab": 3e9 + i * 3e7,
                "debt_to_assets": 0.4 + i * 0.02,
            }
            for i, ed in enumerate(["20240331", "20240630", "20240930", "20241231"])
        ]
        return pd.DataFrame(rows)

    async def get_cashflow(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        # Deterministic inline builder — avoids the LLM-based legacy generate_cashflow.
        # 4 quarters; preserves CashFlowRule's expectations on n_cashflow_act / end_date.
        # n_cashflow_act intentionally decreasing to keep yellow-signal coverage stable.
        #
        # Mock column contract (intentionally minimal):
        # 提供:ts_code / end_date / n_cashflow_act / n_cashflow_inv_act / n_cash_flows_fnc_act
        #       — 覆盖 Task 1/8 CashFlowRule 当前需求.
        # 不提供:Tushare cashflow 真实接口约 80 列(c_paid_for_invest / c_inf_fr_operate_a /
        #       c_paid_to_for_empl / c_pay_dist_dpcp_int_exp / free_cashflow / ...).
        # 未来如果某 rule 需要 free_cashflow 等列, 扩 fixture row dict, 不要回到
        # LLM-based generate_cashflow — 那条路径不 deterministic.
        rows = [
            {
                "ts_code": ts_code,
                "end_date": ed,
                "n_cashflow_act": 5e8 - i * 2e7,  # 经营性现金流 (递减触发 yellow)
                "n_cashflow_inv_act": -2e8,
                "n_cash_flows_fnc_act": 1e8,  # 注:列名带 s_ — Tushare Pro 历史命名
            }
            for i, ed in enumerate(["20240331", "20240630", "20240930", "20241231"])
        ]
        return pd.DataFrame(rows)

    async def get_stk_holdernumber(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        return await self._ensure_inner().generate_stk_holdernumber(
            ts_code=ts_code, end_date=end_date
        )

    async def get_disclosure_date(
        self, *, ts_code: str | None, start: str, end: str
    ) -> pd.DataFrame:
        return await self._ensure_inner().generate_disclosure_date(
            ts_code=ts_code, start=start, end=end
        )

    async def get_anns(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        return await self._ensure_inner().generate_anns(ts_code=ts_code, start=start, end=end)

    # -------------------------------------------------------------------
    # v0.8.5 — 6 个新接口的 deterministic mock fixtures
    # 直接 hardcode (option a) 避免 LLM 依赖, 利于 unit-layer LLM_MODE=none 守卫.
    # -------------------------------------------------------------------

    async def get_daily_basic(self, *, ts_code: str, trade_date: str | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": [ts_code],
                "trade_date": [trade_date or "20241231"],
                "pe": [64.19],
                "pb": [12.5],
                "ps": [22.0],
                "dv_ratio": [1.95],  # 股息率 %
                "total_mv": [22000e8],  # 总市值 (元)
                "circ_mv": [22000e8],  # 流通市值
                "turnover_rate": [0.32],
            }
        )

    async def get_pe_history(
        self, *, ts_code: str, years_back: int = 5, current_pe: float | None = None
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": [ts_code],
                "current_pe": [current_pe if current_pe is not None else 64.19],
                "historical_percentile": [0.78],  # PE 处于近 N 年 78% 分位
                "min_pe": [22.0],
                "max_pe": [78.5],
                "median_pe": [38.2],
            }
        )

    async def get_forecast(self, *, ts_code: str, period: str | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": [ts_code],
                "period": [period or "20241231"],
                "type": ["预增"],
                "p_change_min": [12.0],  # 预告净利润下限增长率 %
                "p_change_max": [18.0],
            }
        )

    async def get_dividend_history(self, *, ts_code: str, years_back: int = 5) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": [ts_code] * 5,
                "ann_date": ["20240515", "20230515", "20220515", "20210515", "20200515"],
                "cash_div": [29.5, 25.9, 21.7, 19.3, 17.0],  # 每股现金分红 (元)
                "stk_div": [0.0, 0.0, 0.0, 0.0, 0.0],  # 每股送转
            }
        )

    async def get_holder_change(self, *, ts_code: str, years_back: int = 2) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": [ts_code] * 4,
                "end_date": ["20240331", "20230930", "20230331", "20220930"],
                "holder_num": [83000, 85500, 88000, 91200],
            }
        )

    async def get_money_flow(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": [ts_code],
                "trade_date": [end_date],
                "buy_lg_amount": [3.5e8],
                "sell_lg_amount": [3.2e8],
                "buy_md_amount": [1.8e8],
                "sell_md_amount": [1.6e8],
            }
        )

    async def get_index_daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        # deterministic:两日,当日 -0.80%
        return pd.DataFrame(
            {
                "ts_code": [ts_code, ts_code],
                "trade_date": ["20261113", "20261114"],
                "close": [4000.0, 3968.0],
                "pre_close": [4010.0, 4000.0],
                "pct_chg": [-0.25, -0.80],
            }
        )

    async def get_fund_nav(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        # deterministic:两日净值,当日 -1.0%
        return pd.DataFrame(
            {
                "ts_code": [ts_code, ts_code],
                "nav_date": ["20261113", "20261114"],
                "unit_nav": [2.500, 2.475],
            }
        )

    async def get_fund_basic(self, *, ts_code: str) -> pd.DataFrame:
        # deterministic:股票型示例基金
        return pd.DataFrame(
            {
                "ts_code": [ts_code],
                "name": ["示例基金"],
                "fund_type": ["股票型"],
                "market": ["O"],
            }
        )

    async def get_stock_basic(self, *, ts_code: str | None = None) -> pd.DataFrame:
        # deterministic stub.
        # ts_code=None → 返回5只示例股票(模拟批量拉取所有在市股);
        # ts_code 指定 → 返回该股单行(原有行为,向后兼容).
        if ts_code is None:
            return pd.DataFrame(
                {
                    "ts_code": ["600519.SH", "000858.SZ", "000568.SZ", "600036.SH", "601398.SH"],
                    "name": ["贵州茅台", "五粮液", "泸州老窖", "招商银行", "工商银行"],
                    "industry": ["白酒", "白酒", "白酒", "银行", "银行"],
                    "list_date": ["20010827", "19980427", "19941118", "20020409", "20061027"],
                }
            )
        return pd.DataFrame(
            {
                "ts_code": [ts_code],
                "name": ["贵州茅台"],
                "industry": ["白酒"],
                "list_date": ["20010827"],
            }
        )

    async def get_sw_index_daily(self, *, index_code: str, trade_date: str) -> pd.DataFrame:
        # deterministic:固定 -3.0% 当日涨跌(列名对齐真实 sw_daily:pct_change,非 pct_chg)
        return pd.DataFrame(
            {
                "ts_code": [index_code],
                "trade_date": [trade_date],
                "pct_change": [-3.0],
            }
        )

    async def get_trade_cal(self, *, start: str, end: str) -> pd.DataFrame:
        # 交易日历是确定性历法,绝不走 LLM 生成(见 mock-tushare-adapter-is-llm-backed)。
        from app.services.trade_calendar import build_calendar_df

        return build_calendar_df(start, end)

    async def get_index_weight(
        self,
        *,
        index_code: str,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        # deterministic stub: 返回5只中证800成分股示例.
        # trade_date / start_date / end_date 参数接受但忽略(stub 不区分日期).
        ref_date = trade_date or end_date or "20260529"
        return pd.DataFrame(
            {
                "index_code": [index_code] * 5,
                "con_code": [
                    "600519.SH",
                    "000858.SZ",
                    "000568.SZ",
                    "600036.SH",
                    "601398.SH",
                ],
                "trade_date": [ref_date] * 5,
                "weight": [2.5, 1.8, 1.2, 1.5, 2.0],
            }
        )

    async def aclose(self) -> None:
        """No-op: legacy MockTushareService has no connections to close."""
        pass
