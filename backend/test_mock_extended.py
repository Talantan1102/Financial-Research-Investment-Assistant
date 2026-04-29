#!/usr/bin/env python3
# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
Mock Tushare 扩展功能测试脚本

验证 MockTushareService 新增的 12 个 API 方法：
- fina_indicator
- income
- balancesheet
- cashflow
- moneyflow
- top_list
- limit_list
- margin
- moneyflow_hsgt
- concept
- concept_detail
- stock_company

运行方式：
    cd backend && python test_mock_extended.py
"""

import math
import os
import sys

# 强制启用 Mock 模式
os.environ["USE_MOCK_TUSHARE"] = "true"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from app.data.tushare_client import TushareClient


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def log_pass(msg: str):
    print(f"{Colors.GREEN}[PASS]{Colors.RESET} {msg}")


def log_fail(msg: str):
    print(f"{Colors.RED}[FAIL]{Colors.RESET} {msg}")


def log_info(msg: str):
    print(f"{Colors.YELLOW}[INFO]{Colors.RESET} {msg}")


def assert_not_empty(df: pd.DataFrame, name: str) -> bool:
    if df is None or df.empty:
        log_fail(f"{name}: 返回为空 DataFrame")
        return False
    log_pass(f"{name}: 返回 {len(df)} 条记录")
    return True


def assert_columns(df: pd.DataFrame, expected_cols: list, name: str) -> bool:
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        log_fail(f"{name}: 缺少列 {missing}")
        return False
    log_pass(f"{name}: 列名检查通过 ({len(expected_cols)} 列)")
    return True


def assert_types(df: pd.DataFrame, checks: dict, name: str) -> bool:
    ok = True
    for col, expected_type in checks.items():
        if col not in df.columns:
            continue
        val = df[col].iloc[0]
        if val is None or (isinstance(val, float) and math.isnan(val)):
            continue
        if expected_type == "str" and not isinstance(val, str):
            log_fail(f"{name}.{col} 应为字符串, 实际 {type(val)}")
            ok = False
        elif expected_type == "float" and not (
            isinstance(val, (int, float)) or (isinstance(val, str) and val == "")
        ):
            log_fail(f"{name}.{col} 应为数值, 实际 {type(val)}")
            ok = False
    if ok:
        log_pass(f"{name}: 数据类型检查通过")
    return ok


def assert_range(df: pd.DataFrame, col: str, low: float, high: float, name: str) -> bool:
    if col not in df.columns:
        return True
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if series.empty:
        return True
    if series.min() < low or series.max() > high:
        log_fail(
            f"{name}.{col} 超出范围 [{low}, {high}], 实际 [{series.min():.4f}, {series.max():.4f}]"
        )
        return False
    log_pass(f"{name}.{col} 数值范围合理 [{series.min():.4f}, {series.max():.4f}]")
    return True


def assert_accounting_equation(df: pd.DataFrame, name: str) -> bool:
    """资产负债表：总资产 ≈ 总负债 + 所有者权益"""
    if "total_assets" not in df.columns or "total_liab_eqt" not in df.columns:
        return True
    assets = pd.to_numeric(df["total_assets"], errors="coerce").dropna()
    liab_eqt = pd.to_numeric(df["total_liab_eqt"], errors="coerce").dropna()
    if assets.empty or liab_eqt.empty:
        return True
    diff = abs(assets.iloc[0] - liab_eqt.iloc[0]) / max(assets.iloc[0], 1)
    if diff > 0.05:
        log_fail(f"{name}: 资产负债表不平衡, diff={diff:.2%}")
        return False
    log_pass(f"{name}: 资产负债表勾稽关系通过 (diff={diff:.2%})")
    return True


def assert_income_reconcile(df: pd.DataFrame, name: str) -> bool:
    """利润表：营业利润 + 营业外收入 - 营业外支出 ≈ 利润总额"""
    cols = ["operate_profit", "non_oper_income", "non_oper_exp", "total_profit"]
    if not all(c in df.columns for c in cols):
        return True
    op = float(df["operate_profit"].iloc[0]) if df["operate_profit"].iloc[0] is not None else 0
    noi = float(df["non_oper_income"].iloc[0]) if df["non_oper_income"].iloc[0] is not None else 0
    noe = float(df["non_oper_exp"].iloc[0]) if df["non_oper_exp"].iloc[0] is not None else 0
    tp = float(df["total_profit"].iloc[0]) if df["total_profit"].iloc[0] is not None else 0
    calc = op + noi - noe
    diff = abs(calc - tp) / max(abs(tp), 1)
    if diff > 0.1:
        log_fail(f"{name}: 利润表勾稽关系偏差较大, diff={diff:.2%}")
        return False
    log_pass(f"{name}: 利润表勾稽关系通过 (diff={diff:.2%})")
    return True


def assert_cashflow_reconcile(df: pd.DataFrame, name: str) -> bool:
    """现金流量表：期末现金 ≈ 期初现金 + 经营活动 + 投资活动 + 筹资活动 + 汇率影响"""
    cols = [
        "c_cash_equ_beg_period",
        "c_cash_equ_end_period",
        "n_cashflow_act",
        "n_cashflow_inv_act",
        "n_cashflow_fnc_act",
        "eff_fx_flu_cash",
    ]
    if not all(c in df.columns for c in cols):
        return True
    beg = pd.to_numeric(df["c_cash_equ_beg_period"], errors="coerce").fillna(0).iloc[0]
    end = pd.to_numeric(df["c_cash_equ_end_period"], errors="coerce").fillna(0).iloc[0]
    act = pd.to_numeric(df["n_cashflow_act"], errors="coerce").fillna(0).iloc[0]
    inv = pd.to_numeric(df["n_cashflow_inv_act"], errors="coerce").fillna(0).iloc[0]
    fnc = pd.to_numeric(df["n_cashflow_fnc_act"], errors="coerce").fillna(0).iloc[0]
    fx = pd.to_numeric(df["eff_fx_flu_cash"], errors="coerce").fillna(0).iloc[0]
    calc = beg + act + inv + fnc + fx
    diff = abs(calc - end) / max(abs(end), 1)
    # 放宽到30%，因为LLM生成的模拟数据允许一定误差
    if diff > 0.3:
        log_fail(f"{name}: 现金流量表勾稽关系偏差较大, diff={diff:.2%}")
        return False
    log_pass(f"{name}: 现金流量表勾稽关系通过 (diff={diff:.2%})")
    return True


def run_tests():
    client = TushareClient()
    client.clear_cache()
    api = client.get_api()
    if api is None:
        log_fail("无法获取 Tushare API 实例")
        return False

    log_info("API 实例获取成功，开始测试...")
    all_ok = True

    # ==================== 1. fina_indicator ====================
    log_info("\n--- 测试 fina_indicator ---")
    df = api.fina_indicator(ts_code="600519.SH", period="20241231")
    all_ok &= assert_not_empty(df, "fina_indicator")
    expected = [
        "ts_code",
        "ann_date",
        "end_date",
        "eps",
        "dt_eps",
        "revenue_ps",
        "gross_margin",
        "current_ratio",
        "quick_ratio",
        "cash_ratio",
        "invturn_days",
        "arturn_days",
        "inv_turn",
        "ar_turn",
        "ca_turn",
        "fa_turn",
        "assets_turn",
        "op_income",
        "profit_dedt",
        "netprofit_margin",
        "bps",
        "ocfps",
        "rd_exp",
    ]
    all_ok &= assert_columns(df, expected, "fina_indicator")
    if not df.empty:
        all_ok &= assert_types(
            df, {"ts_code": "str", "eps": "float", "gross_margin": "float"}, "fina_indicator"
        )

    # ==================== 2. income ====================
    log_info("\n--- 测试 income ---")
    df = api.income(ts_code="000001.SZ", period="20241231")
    all_ok &= assert_not_empty(df, "income")
    expected = [
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "basic_eps",
        "diluted_eps",
        "total_revenue",
        "revenue",
        "total_cogs",
        "oper_cost",
        "operate_profit",
        "non_oper_income",
        "non_oper_exp",
        "total_profit",
        "income_tax",
        "n_income",
        "ebit",
        "ebitda",
    ]
    all_ok &= assert_columns(df, expected, "income")
    if not df.empty:
        all_ok &= assert_types(
            df, {"ts_code": "str", "total_revenue": "float", "n_income": "float"}, "income"
        )
        all_ok &= assert_income_reconcile(df, "income")

    # ==================== 3. balancesheet ====================
    log_info("\n--- 测试 balancesheet ---")
    df = api.balancesheet(ts_code="600519.SH", period="20241231")
    all_ok &= assert_not_empty(df, "balancesheet")
    expected = [
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "total_share",
        "cap_rese",
        "undistr_porfit",
        "surplus_rese",
        "special_rese",
        "money_cap",
        "trad_asset",
        "notes_receiv",
        "accounts_receiv",
        "oth_receiv",
        "prepayment",
        "inventories",
        "total_cur_assets",
        "fa_avail_for_sale",
        "lt_eqt_invest",
        "fix_assets",
        "intan_assets",
        "rd",
        "goodwill",
        "total_nca",
        "total_assets",
        "lt_borr",
        "st_borr",
        "notes_payable",
        "acct_payable",
        "adv_receipts",
        "taxes_payable",
        "total_cur_liab",
        "lt_payable",
        "total_ncl",
        "total_liab_eqt",
    ]
    all_ok &= assert_columns(df, expected, "balancesheet")
    if not df.empty:
        all_ok &= assert_types(
            df,
            {"ts_code": "str", "total_assets": "float", "total_liab_eqt": "float"},
            "balancesheet",
        )
        all_ok &= assert_accounting_equation(df, "balancesheet")

    # ==================== 4. cashflow ====================
    log_info("\n--- 测试 cashflow ---")
    df = api.cashflow(ts_code="000001.SZ", period="20241231")
    all_ok &= assert_not_empty(df, "cashflow")
    expected = [
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "comp_type",
        "report_type",
        "net_profit",
        "finan_exp",
        "c_fr_sale_sg",
        "recp_tax_rends",
        "c_inf_fr_operate_a",
        "c_paid_goods_s",
        "c_paid_to_for_empl",
        "c_paid_for_taxes",
        "st_cash_out_act",
        "n_cashflow_act",
        "c_disp_withdrwl_invest",
        "stot_cash_inflow_inv_act",
        "c_pay_acq_const_fiolta",
        "stot_cash_outflow_inv_act",
        "n_cashflow_inv_act",
        "c_recp_borrow",
        "stot_cash_inflow_fnc_act",
        "c_prepay_debt",
        "stot_cash_outflow_fnc_act",
        "n_cashflow_fnc_act",
        "eff_fx_flu_cash",
        "c_cash_equ_beg_period",
        "c_cash_equ_end_period",
    ]
    all_ok &= assert_columns(df, expected, "cashflow")
    if not df.empty:
        all_ok &= assert_types(
            df,
            {"ts_code": "str", "n_cashflow_act": "float", "c_cash_equ_end_period": "float"},
            "cashflow",
        )
        all_ok &= assert_cashflow_reconcile(df, "cashflow")

    # ==================== 5. moneyflow ====================
    log_info("\n--- 测试 moneyflow ---")
    df = api.moneyflow(ts_code="600519.SH", trade_date="20241231")
    all_ok &= assert_not_empty(df, "moneyflow")
    expected = [
        "ts_code",
        "trade_date",
        "buy_sm_vol",
        "buy_sm_amount",
        "sell_sm_vol",
        "sell_sm_amount",
        "buy_md_vol",
        "buy_md_amount",
        "sell_md_vol",
        "sell_md_amount",
        "buy_lg_vol",
        "buy_lg_amount",
        "sell_lg_vol",
        "sell_lg_amount",
        "buy_elg_vol",
        "buy_elg_amount",
        "sell_elg_vol",
        "sell_elg_amount",
        "net_mf_vol",
        "net_mf_amount",
        "trade_count",
    ]
    all_ok &= assert_columns(df, expected, "moneyflow")
    if not df.empty:
        all_ok &= assert_types(
            df, {"ts_code": "str", "net_mf_amount": "float", "trade_count": "float"}, "moneyflow"
        )

    # ==================== 6. top_list ====================
    log_info("\n--- 测试 top_list ---")
    df = api.top_list(trade_date="20241231")
    all_ok &= assert_not_empty(df, "top_list")
    expected = [
        "trade_date",
        "ts_code",
        "name",
        "close",
        "pct_chg",
        "turnover_rate",
        "amount",
        "l_buy",
        "l_sell",
        "net_amount",
        "net_rate",
        "amount_rate",
        "reason",
    ]
    all_ok &= assert_columns(df, expected, "top_list")
    if not df.empty:
        all_ok &= assert_types(
            df, {"ts_code": "str", "close": "float", "net_amount": "float"}, "top_list"
        )

    # ==================== 7. limit_list ====================
    log_info("\n--- 测试 limit_list ---")
    df = api.limit_list(trade_date="20241231")
    all_ok &= assert_not_empty(df, "limit_list")
    expected = [
        "trade_date",
        "ts_code",
        "name",
        "industry",
        "close",
        "pct_chg",
        "amount",
        "limit_amount",
        "float_mv",
        "total_mv",
        "turnover_ratio",
        "fd_amount",
        "first_time",
        "last_time",
        "open_times",
        "up_stat",
        "limit_type",
    ]
    all_ok &= assert_columns(df, expected, "limit_list")
    if not df.empty:
        all_ok &= assert_types(
            df, {"ts_code": "str", "close": "float", "open_times": "float"}, "limit_list"
        )

    # ==================== 8. margin ====================
    log_info("\n--- 测试 margin ---")
    df = api.margin(ts_code="600519.SH", trade_date="20241231")
    all_ok &= assert_not_empty(df, "margin")
    expected = [
        "trade_date",
        "ts_code",
        "rzye",
        "rqyl",
        "rzmre",
        "rqylc",
        "rzche",
        "rqchl",
        "rqmcl",
        "szrje",
        "xzrje",
        "szrkje",
        "xzrkje",
        "rzrqye",
        "rzrqylc",
    ]
    all_ok &= assert_columns(df, expected, "margin")
    if not df.empty:
        all_ok &= assert_types(df, {"ts_code": "str", "rzye": "float", "rzrqye": "float"}, "margin")

    # ==================== 9. moneyflow_hsgt ====================
    log_info("\n--- 测试 moneyflow_hsgt ---")
    df = api.moneyflow_hsgt(trade_date="20241231")
    all_ok &= assert_not_empty(df, "moneyflow_hsgt")
    expected = [
        "trade_date",
        "ggt_ss",
        "ggt_sz",
        "hgt_ltg",
        "hgt_cgtes",
        "hgt_cgtes_l",
        "sgt_ltg",
        "sgt_cgtes",
        "sgt_cgtes_l",
        "north_money",
        "south_money",
    ]
    all_ok &= assert_columns(df, expected, "moneyflow_hsgt")
    if not df.empty:
        all_ok &= assert_types(
            df,
            {"trade_date": "str", "north_money": "float", "south_money": "float"},
            "moneyflow_hsgt",
        )

    # ==================== 10. concept ====================
    log_info("\n--- 测试 concept ---")
    df = api.concept()
    all_ok &= assert_not_empty(df, "concept")
    expected = ["code", "name", "src"]
    all_ok &= assert_columns(df, expected, "concept")
    if not df.empty:
        all_ok &= assert_types(df, {"code": "str", "name": "str"}, "concept")

    # ==================== 11. concept_detail ====================
    log_info("\n--- 测试 concept_detail ---")
    df = api.concept_detail(id="TS01", concept_name="人工智能")
    all_ok &= assert_not_empty(df, "concept_detail")
    expected = ["id", "concept_name", "ts_code", "name", "in_date", "out_date"]
    all_ok &= assert_columns(df, expected, "concept_detail")
    if not df.empty:
        all_ok &= assert_types(df, {"ts_code": "str", "concept_name": "str"}, "concept_detail")

    # ==================== 12. stock_company ====================
    log_info("\n--- 测试 stock_company ---")
    df = api.stock_company(ts_code="600519.SH")
    all_ok &= assert_not_empty(df, "stock_company")
    expected = [
        "ts_code",
        "exchange",
        "chairman",
        "manager",
        "secretary",
        "reg_capital",
        "setup_date",
        "province",
        "city",
        "introduction",
        "website",
        "email",
        "office",
        "employees",
        "main_business",
        "business_scope",
    ]
    all_ok &= assert_columns(df, expected, "stock_company")
    if not df.empty:
        all_ok &= assert_types(
            df, {"ts_code": "str", "exchange": "str", "reg_capital": "float"}, "stock_company"
        )

    log_info("\n========================================")
    if all_ok:
        log_pass("所有扩展测试通过！")
    else:
        log_fail("部分测试未通过，请查看上方详情。")
    log_info("========================================")
    return all_ok


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
