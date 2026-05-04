"""Mock Tushare 服务

利用大模型能力生成模拟的 Tushare API 数据，格式与真实 Tushare API 返回格式完全一致。
用于降低 API 调用成本，同时保留切换到真实 API 的能力。
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from app.services.llm_service import LLMService


class DailyDataItem(BaseModel):
    """日K线数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    trade_date: str = Field(..., pattern=r"^\d{8}$")
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    pre_close: float = Field(..., gt=0)
    change: float
    pct_chg: float
    vol: float = Field(..., ge=0)
    amount: float = Field(..., ge=0)

    @field_validator("high")
    @classmethod
    def validate_high(cls, v: float, info) -> float:
        values = info.data
        if "open" in values and "close" in values and "low" in values:
            max_price = max(values.get("open", 0), values.get("close", 0), values.get("low", 0))
            if v < max_price:
                raise ValueError(f"high ({v}) must be >= max of open/close/low ({max_price})")
        return v

    @field_validator("low")
    @classmethod
    def validate_low(cls, v: float, info) -> float:
        values = info.data
        if "open" in values and "close" in values and "high" in values:
            min_price = min(
                values.get("open", float("inf")),
                values.get("close", float("inf")),
                values.get("high", float("inf")),
            )
            if v > min_price:
                raise ValueError(f"low ({v}) must be <= min of open/close/high ({min_price})")
        return v


class DailyDataResponse(BaseModel):
    """日K线数据响应"""

    data: list[DailyDataItem]


class DailyBasicItem(BaseModel):
    """每日指标数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    trade_date: str = Field(..., pattern=r"^\d{8}$")
    close: float = Field(..., gt=0)
    turnover_rate: float | None = Field(None, ge=0)
    turnover_rate_f: float | None = Field(None, ge=0)
    volume_ratio: float | None = Field(None, ge=0)
    pe: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    ps: float | None = None
    ps_ttm: float | None = None
    dv_ratio: float | None = None
    dv_ttm: float | None = None
    total_share: float | None = Field(None, ge=0)
    float_share: float | None = Field(None, ge=0)
    free_share: float | None = Field(None, ge=0)
    total_mv: float | None = Field(None, ge=0)
    circ_mv: float | None = Field(None, ge=0)


class DailyBasicResponse(BaseModel):
    """每日指标数据响应"""

    data: list[DailyBasicItem]


class StockBasicItem(BaseModel):
    """股票基本信息数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    symbol: str = Field(..., pattern=r"^\d{6}$")
    name: str = Field(..., min_length=1, max_length=20)
    area: str | None = None
    industry: str | None = None
    fullname: str | None = None
    enname: str | None = None
    cnspell: str | None = None
    market: str | None = None
    exchange: str | None = Field(None, pattern=r"^(SSE|SZE|BSE)$")
    curr_type: str | None = None
    list_status: str | None = Field(None, pattern=r"^(L|D|P)$")
    list_date: str | None = Field(None, pattern=r"^\d{8}$")
    delist_date: str | None = None
    is_hs: str | None = None


class StockBasicResponse(BaseModel):
    """股票基本信息数据响应"""

    data: list[StockBasicItem]


class FinaIndicatorItem(BaseModel):
    """财务指标数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    ann_date: str = Field(..., pattern=r"^\d{8}$")
    end_date: str = Field(..., pattern=r"^\d{8}$")
    eps: float | None = None
    dt_eps: float | None = None
    total_revenue_ps: float | None = None
    revenue_ps: float | None = None
    capital_rese: float | None = None
    undist_profit: float | None = None
    extra_item: float | None = None
    profit_dedt: float | None = None
    gross_margin: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    cash_ratio: float | None = None
    invturn_days: float | None = None
    arturn_days: float | None = None
    inv_turn: float | None = None
    ar_turn: float | None = None
    ca_turn: float | None = None
    fa_turn: float | None = None
    assets_turn: float | None = None
    op_income: float | None = None
    valuechange_income: float | None = None
    interst_income: float | None = None
    daa_exp: float | None = None
    ebit: float | None = None
    ebitda: float | None = None
    fcff: float | None = None
    fcfe: float | None = None
    current_exint: float | None = None
    noncurrent_exint: float | None = None
    interestdebt: float | None = None
    netdebt: float | None = None
    tangible_asset: float | None = None
    working_capital: float | None = None
    networking_capital: float | None = None
    invest_capital: float | None = None
    retained_earnings: float | None = None
    diluted2_eps: float | None = None
    bps: float | None = None
    ocfps: float | None = None
    retainps: float | None = None
    cfps: float | None = None
    ebit_ps: float | None = None
    fcff_ps: float | None = None
    fcfe_ps: float | None = None
    netprofit_margin: float | None = None
    grossprofit_margin: float | None = None
    cogs_of_sales: float | None = None
    expense_of_sales: float | None = None
    profit_to_gr: float | None = None
    saleexp_to_gr: float | None = None
    adminexp_of_gr: float | None = None
    finaexp_of_gr: float | None = None
    exclexp_of_gr: float | None = None
    ocf_to_gr: float | None = None
    ocf_to_or: float | None = None
    q_sales_yoy: float | None = None
    q_op_qoq: float | None = None
    equity_yoy: float | None = None
    rd_exp: float | None = None


class FinaIndicatorResponse(BaseModel):
    """财务指标数据响应"""

    data: list[FinaIndicatorItem]


class IncomeItem(BaseModel):
    """利润表数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    ann_date: str = Field(..., pattern=r"^\d{8}$")
    f_ann_date: str | None = Field(None, pattern=r"^\d{8}$")
    end_date: str = Field(..., pattern=r"^\d{8}$")
    report_type: str | None = None
    comp_type: str | None = None
    basic_eps: float | None = None
    diluted_eps: float | None = None
    total_revenue: float | None = None
    revenue: float | None = None
    int_income: float | None = None
    prem_earned: float | None = None
    comm_income: float | None = None
    n_commis_income: float | None = None
    n_oi: float | None = None
    other_business_income: float | None = None
    total_cogs: float | None = None
    oper_cost: float | None = None
    int_exp: float | None = None
    comm_exp: float | None = None
    prem_refund: float | None = None
    compens_payout: float | None = None
    reser_insur_liab: float | None = None
    div_payt: float | None = None
    reins_exp: float | None = None
    oper_exp: float | None = None
    compens_payout_refu: float | None = None
    insur_reser_refu: float | None = None
    reins_cost_refund: float | None = None
    other_bus_cost: float | None = None
    operate_profit: float | None = None
    non_oper_income: float | None = None
    non_oper_exp: float | None = None
    nca_disploss: float | None = None
    total_profit: float | None = None
    income_tax: float | None = None
    n_income: float | None = None
    n_income_attr_p: float | None = None
    minority_gain: float | None = None
    oth_compr_income: float | None = None
    t_compr_income: float | None = None
    compr_inc_attr_p: float | None = None
    compr_inc_attr_m: float | None = None
    ebit: float | None = None
    ebitda: float | None = None
    insurance_exp: float | None = None
    undist_profit: float | None = None
    distable_profit: float | None = None


class IncomeResponse(BaseModel):
    """利润表数据响应"""

    data: list[IncomeItem]


class BalanceSheetItem(BaseModel):
    """资产负债表数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    ann_date: str = Field(..., pattern=r"^\d{8}$")
    f_ann_date: str | None = Field(None, pattern=r"^\d{8}$")
    end_date: str = Field(..., pattern=r"^\d{8}$")
    report_type: str | None = None
    comp_type: str | None = None
    total_share: float | None = None
    cap_rese: float | None = None
    undistr_porfit: float | None = None
    surplus_rese: float | None = None
    special_rese: float | None = None
    money_cap: float | None = None
    trad_asset: float | None = None
    notes_receiv: float | None = None
    accounts_receiv: float | None = None
    oth_receiv: float | None = None
    prepayment: float | None = None
    div_receiv: float | None = None
    int_receiv: float | None = None
    inventories: float | None = None
    amor_exp: float | None = None
    nca_within_1y: float | None = None
    sett_rsrv: float | None = None
    loanto_oth_bank_fi: float | None = None
    premium_receiv: float | None = None
    reinsur_receiv: float | None = None
    reinsur_res_receiv: float | None = None
    pur_resale_fa: float | None = None
    oth_cur_assets: float | None = None
    total_cur_assets: float | None = None
    fa_avail_for_sale: float | None = None
    htm_invest: float | None = None
    lt_eqt_invest: float | None = None
    invest_real_estate: float | None = None
    time_deposits: float | None = None
    oth_assets: float | None = None
    lt_rec: float | None = None
    fix_assets: float | None = None
    cip: float | None = None
    const_materials: float | None = None
    fix_assets_disp: float | None = None
    produc_bio_assets: float | None = None
    oil_and_gas_assets: float | None = None
    intan_assets: float | None = None
    rd: float | None = None
    goodwill: float | None = None
    lt_amor_exp: float | None = None
    defer_tax_assets: float | None = None
    decr_in_disbur: float | None = None
    oth_nca: float | None = None
    total_nca: float | None = None
    cash_reser_cb: float | None = None
    depos_in_oth_bfi: float | None = None
    prec_metals: float | None = None
    deriv_assets: float | None = None
    dp_receiv: float | None = None
    total_assets: float | None = None
    lt_borr: float | None = None
    st_borr: float | None = None
    cb_borr: float | None = None
    depos_ib_deposits: float | None = None
    loan_oth_bank: float | None = None
    trading_fl: float | None = None
    notes_payable: float | None = None
    acct_payable: float | None = None
    adv_receipts: float | None = None
    sold_for_repur_fa: float | None = None
    comm_payable: float | None = None
    payroll_payable: float | None = None
    taxes_payable: float | None = None
    int_payable: float | None = None
    div_payable: float | None = None
    oth_payable: float | None = None
    acc_exp: float | None = None
    deferred_inc: float | None = None
    st_bonds_payable: float | None = None
    payable_to_reinsurer: float | None = None
    rsrv_insur_cont: float | None = None
    acting_trading_sec: float | None = None
    acting_uw_sec: float | None = None
    non_cur_liab_due_1y: float | None = None
    oth_cur_liab: float | None = None
    total_cur_liab: float | None = None
    lt_payable: float | None = None
    specific_payables: float | None = None
    estimated_liab: float | None = None
    defer_tax_liab: float | None = None
    defer_inc_non_cur_liab: float | None = None
    oth_ncl: float | None = None
    total_ncl: float | None = None
    depos_oth_bfi: float | None = None
    deriv_liab: float | None = None
    reserves: float | None = None
    undur_por_reserves: float | None = None
    money_cap_reser: float | None = None
    owed_invest: float | None = None
    oth_eqt_tools_p: float | None = None
    total_liab_eqt: float | None = None
    tot_liab_shrhldr_eqy: float | None = None
    cap_rese_ps: float | None = None
    cash_net_rase: float | None = None
    bfe_texpr: float | None = None
    saleexp_fix: float | None = None
    bddp: float | None = None
    dva_depr: float | None = None
    fin_exp_int_inc: float | None = None
    transfer_to_sundry: float | None = None
    total_profit: float | None = None
    profit_for_owner: float | None = None


class BalanceSheetResponse(BaseModel):
    """资产负债表数据响应"""

    data: list[BalanceSheetItem]


class CashFlowItem(BaseModel):
    """现金流量表数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    ann_date: str = Field(..., pattern=r"^\d{8}$")
    f_ann_date: str | None = Field(None, pattern=r"^\d{8}$")
    end_date: str = Field(..., pattern=r"^\d{8}$")
    comp_type: str | None = None
    report_type: str | None = None
    net_profit: float | None = None
    finan_exp: float | None = None
    c_fr_sale_sg: float | None = None
    recp_tax_rends: float | None = None
    n_depos_incr_fi: float | None = None
    n_incr_loans_cb: float | None = None
    n_inc_borr_oth_fi: float | None = None
    prem_fr_orig_contr: float | None = None
    n_incr_insured_dep: float | None = None
    n_reinsur_prem: float | None = None
    incr_illness_res: float | None = None
    n_incr_disp_tfa: float | None = None
    ifc_cash_incr: float | None = None
    n_incr_loans_oth_bank: float | None = None
    n_cap_incr_repur: float | None = None
    c_fr_oth_operate_a: float | None = None
    c_inf_fr_operate_a: float | None = None
    c_paid_goods_s: float | None = None
    c_paid_to_for_empl: float | None = None
    c_paid_for_taxes: float | None = None
    n_incr_clt_loan_adv: float | None = None
    n_incr_dep_cbob: float | None = None
    c_pay_claims_orig_inco: float | None = None
    pay_handling_chrg: float | None = None
    c_pay_all_tax: float | None = None
    c_paid_to_oth_operator_pur: float | None = None
    st_cash_out_act: float | None = None
    s_mjr_subsidiary_oth_bsn: float | None = None
    stot_cash_out_act: float | None = None
    n_cashflow_act: float | None = None
    oth_recp_ral_inv_act: float | None = None
    c_disp_withdrwl_invest: float | None = None
    c_recp_return_invest: float | None = None
    n_recp_disp_fiolta: float | None = None
    n_recp_disp_sobu: float | None = None
    stot_cash_inflow_inv_act: float | None = None
    c_pay_acq_const_fiolta: float | None = None
    c_paid_invest: float | None = None
    n_disp_subs_oth_biz: float | None = None
    oth_pay_ral_inv_act: float | None = None
    n_incr_pledge_loan: float | None = None
    stot_cash_outflow_inv_act: float | None = None
    n_cashflow_inv_act: float | None = None
    c_recp_borrow: float | None = None
    proc_issue_shares: float | None = None
    oth_recp_ral_fnc_act: float | None = None
    stot_cash_inflow_fnc_act: float | None = None
    c_prepay_debt: float | None = None
    c_pay_amount_borr_oth_fi: float | None = None
    c_pay_div_prof_int: float | None = None
    stot_cash_outflow_fnc_act: float | None = None
    n_cashflow_fnc_act: float | None = None
    eff_fx_flu_cash: float | None = None
    c_cash_equ_beg_period: float | None = None
    c_cash_equ_end_period: float | None = None
    c_recp_cap_contrib: float | None = None
    incl_dvd_profit_paid_sc_ms: float | None = None
    uncon_invest_loss: float | None = None
    prov_depr_assets: float | None = None
    depr_fa_coga_dpba: float | None = None
    amort_intang_assets: float | None = None
    lt_amort_deferred_exp: float | None = None
    decr_deferred_exp: float | None = None
    incr_acc_exp: float | None = None
    loss_disp_fiolta: float | None = None
    loss_scr_fa: float | None = None
    loss_fv_chg: float | None = None
    fin_exp: float | None = None
    invest_loss: float | None = None
    decr_deferred_inc_tax_assets: float | None = None
    incr_deferred_inc_tax_liab: float | None = None
    decr_inventories: float | None = None
    decr_oper_payable: float | None = None
    incr_oper_payable: float | None = None
    others: float | None = None
    im_net_cashflow_oper_act: float | None = None
    conv_debt_into_cap: float | None = None
    conv_copbonds_due_within_1y: float | None = None
    fa_fnc_leases: float | None = None
    end_bal_cash: float | None = None
    beg_bal_cash: float | None = None
    end_bal_cash_equ: float | None = None
    beg_bal_cash_equ: float | None = None


class CashFlowResponse(BaseModel):
    """现金流量表数据响应"""

    data: list[CashFlowItem]


class MoneyFlowItem(BaseModel):
    """个股资金流向数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    trade_date: str = Field(..., pattern=r"^\d{8}$")
    buy_sm_vol: float | None = None
    buy_sm_amount: float | None = None
    sell_sm_vol: float | None = None
    sell_sm_amount: float | None = None
    buy_md_vol: float | None = None
    buy_md_amount: float | None = None
    sell_md_vol: float | None = None
    sell_md_amount: float | None = None
    buy_lg_vol: float | None = None
    buy_lg_amount: float | None = None
    sell_lg_vol: float | None = None
    sell_lg_amount: float | None = None
    buy_elg_vol: float | None = None
    buy_elg_amount: float | None = None
    sell_elg_vol: float | None = None
    sell_elg_amount: float | None = None
    net_mf_vol: float | None = None
    net_mf_amount: float | None = None
    trade_count: float | None = None


class MoneyFlowResponse(BaseModel):
    """个股资金流向数据响应"""

    data: list[MoneyFlowItem]


class TopListItem(BaseModel):
    """龙虎榜数据项"""

    trade_date: str = Field(..., pattern=r"^\d{8}$")
    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    name: str
    close: float | None = None
    pct_chg: float | None = None
    turnover_rate: float | None = None
    amount: float | None = None
    l_buy: float | None = None
    l_sell: float | None = None
    net_amount: float | None = None
    net_rate: float | None = None
    amount_rate: float | None = None
    reason: str | None = None
    brk_name: str | None = None
    brk_buy: float | None = None
    brk_sell: float | None = None


class TopListResponse(BaseModel):
    """龙虎榜数据响应"""

    data: list[TopListItem]


class LimitListItem(BaseModel):
    """涨停榜数据项"""

    trade_date: str = Field(..., pattern=r"^\d{8}$")
    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    name: str
    industry: str | None = None
    close: float | None = None
    pct_chg: float | None = None
    amount: float | None = None
    limit_amount: float | None = None
    float_mv: float | None = None
    total_mv: float | None = None
    turnover_ratio: float | None = None
    fd_amount: float | None = None
    first_time: str | None = None
    last_time: str | None = None
    open_times: float | None = None
    up_stat: str | None = None
    limit_type: str | None = None
    limit_status: float | None = None


class LimitListResponse(BaseModel):
    """涨停榜数据响应"""

    data: list[LimitListItem]


class MarginItem(BaseModel):
    """融资融券数据项"""

    trade_date: str = Field(..., pattern=r"^\d{8}$")
    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    rzye: float | None = None
    rqyl: float | None = None
    rzmre: float | None = None
    rqylc: float | None = None
    rzche: float | None = None
    rqchl: float | None = None
    rqmcl: float | None = None
    szrje: float | None = None
    xzrje: float | None = None
    szrkje: float | None = None
    xzrkje: float | None = None
    rzrqye: float | None = None
    rzrqylc: float | None = None


class MarginResponse(BaseModel):
    """融资融券数据响应"""

    data: list[MarginItem]


class MoneyFlowHsgtItem(BaseModel):
    """沪深港通资金流向数据项"""

    trade_date: str = Field(..., pattern=r"^\d{8}$")
    ggt_ss: float | None = None
    ggt_sz: float | None = None
    hgt_ltg: float | None = None
    hgt_cgtes: float | None = None
    hgt_cgtes_l: float | None = None
    sgt_ltg: float | None = None
    sgt_cgtes: float | None = None
    sgt_cgtes_l: float | None = None
    north_money: float | None = None
    south_money: float | None = None


class MoneyFlowHsgtResponse(BaseModel):
    """沪深港通资金流向数据响应"""

    data: list[MoneyFlowHsgtItem]


class ConceptItem(BaseModel):
    """概念股分类数据项"""

    code: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    src: str | None = None


class ConceptResponse(BaseModel):
    """概念股分类数据响应"""

    data: list[ConceptItem]


class ConceptDetailItem(BaseModel):
    """概念股明细数据项"""

    id: str | None = None
    concept_name: str = Field(..., min_length=1)
    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    name: str = Field(..., min_length=1)
    in_date: str | None = Field(None, pattern=r"^\d{8}$")
    out_date: str | None = Field(None, pattern=r"^\d{8}$")


class ConceptDetailResponse(BaseModel):
    """概念股明细数据响应"""

    data: list[ConceptDetailItem]


class StockCompanyItem(BaseModel):
    """上市公司基本信息数据项"""

    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    exchange: str | None = Field(None, pattern=r"^(SSE|SZE|BSE)$")
    chairman: str | None = None
    manager: str | None = None
    secretary: str | None = None
    reg_capital: float | None = None
    setup_date: str | None = Field(None, pattern=r"^\d{8}$")
    province: str | None = None
    city: str | None = None
    introduction: str | None = None
    website: str | None = None
    email: str | None = None
    office: str | None = None
    employees: float | None = None
    main_business: str | None = None
    business_scope: str | None = None


class StockCompanyResponse(BaseModel):
    """上市公司基本信息数据响应"""

    data: list[StockCompanyItem]


class MockTushareService:
    """
    Mock Tushare 服务

    使用LLM生成模拟 Tushare 数据，格式与真实 Tushare API 完全一致。
    支持核心数据类型：日K线、每日指标、股票基本信息。
    """

    # 预设股票池，用于生成一致的模拟数据
    MOCK_STOCKS = [
        {
            "ts_code": "000001.SZ",
            "symbol": "000001",
            "name": "平安银行",
            "area": "深圳",
            "industry": "银行",
            "market": "主板",
            "exchange": "SZE",
        },
        {
            "ts_code": "000002.SZ",
            "symbol": "000002",
            "name": "万科A",
            "area": "深圳",
            "industry": "房地产",
            "market": "主板",
            "exchange": "SZE",
        },
        {
            "ts_code": "000333.SZ",
            "symbol": "000333",
            "name": "美的集团",
            "area": "佛山",
            "industry": "家电",
            "market": "主板",
            "exchange": "SZE",
        },
        {
            "ts_code": "000858.SZ",
            "symbol": "000858",
            "name": "五粮液",
            "area": "宜宾",
            "industry": "白酒",
            "market": "主板",
            "exchange": "SZE",
        },
        {
            "ts_code": "002230.SZ",
            "symbol": "002230",
            "name": "科大讯飞",
            "area": "合肥",
            "industry": "软件服务",
            "market": "中小板",
            "exchange": "SZE",
        },
        {
            "ts_code": "002415.SZ",
            "symbol": "002415",
            "name": "海康威视",
            "area": "杭州",
            "industry": "电子",
            "market": "中小板",
            "exchange": "SZE",
        },
        {
            "ts_code": "300750.SZ",
            "symbol": "300750",
            "name": "宁德时代",
            "area": "宁德",
            "industry": "新能源",
            "market": "创业板",
            "exchange": "SZE",
        },
        {
            "ts_code": "600000.SH",
            "symbol": "600000",
            "name": "浦发银行",
            "area": "上海",
            "industry": "银行",
            "market": "主板",
            "exchange": "SSE",
        },
        {
            "ts_code": "600009.SH",
            "symbol": "600009",
            "name": "上海机场",
            "area": "上海",
            "industry": "交通运输",
            "market": "主板",
            "exchange": "SSE",
        },
        {
            "ts_code": "600519.SH",
            "symbol": "600519",
            "name": "贵州茅台",
            "area": "遵义",
            "industry": "白酒",
            "market": "主板",
            "exchange": "SSE",
        },
        {
            "ts_code": "600036.SH",
            "symbol": "600036",
            "name": "招商银行",
            "area": "深圳",
            "industry": "银行",
            "market": "主板",
            "exchange": "SSE",
        },
        {
            "ts_code": "601318.SH",
            "symbol": "601318",
            "name": "中国平安",
            "area": "深圳",
            "industry": "保险",
            "market": "主板",
            "exchange": "SSE",
        },
        {
            "ts_code": "601888.SH",
            "symbol": "601888",
            "name": "中国中免",
            "area": "北京",
            "industry": "旅游",
            "market": "主板",
            "exchange": "SSE",
        },
        {
            "ts_code": "603288.SH",
            "symbol": "603288",
            "name": "海天味业",
            "area": "佛山",
            "industry": "食品",
            "market": "主板",
            "exchange": "SSE",
        },
        {
            "ts_code": "688981.SH",
            "symbol": "688981",
            "name": "中芯国际",
            "area": "上海",
            "industry": "半导体",
            "market": "科创板",
            "exchange": "SSE",
        },
    ]

    # 行业基准价格（用于生成合理的价格范围）
    INDUSTRY_BASE_PRICES = {
        "银行": 15.0,
        "白酒": 200.0,
        "保险": 50.0,
        "房地产": 8.0,
        "家电": 40.0,
        "电子": 35.0,
        "软件服务": 60.0,
        "新能源": 120.0,
        "半导体": 80.0,
        "食品": 50.0,
        "旅游": 35.0,
        "交通运输": 25.0,
    }

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm
        self._stock_map = {s["ts_code"]: s for s in self.MOCK_STOCKS}
        self._symbol_map = {s["symbol"]: s for s in self.MOCK_STOCKS}

    async def _call_llm_async(self, system_msg: str, user_prompt: str) -> str:
        """调用 LLMService，将 system 和 user 消息合并为单一 prompt。

        LLMService.chat 是同步方法，此处用 asyncio.to_thread 包装以兼容
        async 调用方。返回 LLM 响应文本内容。
        """
        combined_prompt = f"{system_msg}\n\n{user_prompt}"
        response = await asyncio.to_thread(self._llm.chat, combined_prompt, "fast")
        return response.content

    def _get_stock_info(self, ts_code: str) -> dict[str, Any] | None:
        """获取股票信息"""
        return self._stock_map.get(ts_code)

    def _get_base_price(self, ts_code: str) -> float:
        """获取股票基准价格"""
        stock = self._get_stock_info(ts_code)
        if stock:
            industry = stock.get("industry", "")
            base = self.INDUSTRY_BASE_PRICES.get(industry, 30.0)
            # 根据代码添加一些随机波动
            code_hash = int(ts_code[:6][-3:])
            return base * (0.8 + (code_hash % 40) / 100)
        return 30.0

    async def generate_daily_data(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        生成日K线数据

        Args:
            ts_code: Tushare格式股票代码，如 "600519.SH"
            start_date: 开始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"

        Returns:
            DataFrame，格式与 Tushare daily 接口一致
        """
        stock = self._get_stock_info(ts_code)
        stock_name = stock["name"] if stock else "未知"
        industry = stock["industry"] if stock else "未知"
        base_price = self._get_base_price(ts_code)

        prompt = self._build_daily_prompt(
            ts_code, stock_name, industry, start_date, end_date, base_price
        )

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回数据，不要包含任何markdown代码块标记或其他说明文字。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        # 使用Pydantic严格校验
        validated_data = self._validate_daily_response(raw_data)

        # 转换为DataFrame
        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            # 确保列顺序与Tushare一致
            columns = [
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "change",
                "pct_chg",
                "vol",
                "amount",
            ]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_daily_basic(
        self, ts_code: str | None = None, trade_date: str | None = None
    ) -> pd.DataFrame:
        """
        生成每日指标数据

        Args:
            ts_code: Tushare格式股票代码，如 "600519.SH"
            trade_date: 交易日期，格式 "YYYYMMDD"

        Returns:
            DataFrame，格式与 Tushare daily_basic 接口一致
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        # 如果指定了个股，生成该股票的数据
        if ts_code:
            stocks = [self._get_stock_info(ts_code)] if self._get_stock_info(ts_code) else []
        else:
            # 生成所有股票的指标数据
            stocks = self.MOCK_STOCKS

        prompt = self._build_daily_basic_prompt(stocks, trade_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_daily_basic_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
                "ts_code",
                "trade_date",
                "close",
                "turnover_rate",
                "turnover_rate_f",
                "volume_ratio",
                "pe",
                "pe_ttm",
                "pb",
                "ps",
                "ps_ttm",
                "dv_ratio",
                "dv_ttm",
                "total_share",
                "float_share",
                "free_share",
                "total_mv",
                "circ_mv",
            ]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_stock_basic(
        self, exchange: str | None = None, list_status: str = "L"
    ) -> pd.DataFrame:
        """
        生成股票基础信息数据

        Args:
            exchange: 交易所，如 "SSE"(上交所), "SZE"(深交所)
            list_status: 上市状态，L-上市，D-退市，P-暂停上市

        Returns:
            DataFrame，格式与 Tushare stock_basic 接口一致
        """
        # 根据过滤条件筛选股票
        stocks = self.MOCK_STOCKS
        if exchange:
            stocks = [s for s in stocks if s.get("exchange") == exchange]

        # 直接返回股票基础信息，不需要调用LLM
        data = []
        for stock in stocks:
            item = {
                "ts_code": stock["ts_code"],
                "symbol": stock["symbol"],
                "name": stock["name"],
                "area": stock.get("area", ""),
                "industry": stock.get("industry", ""),
                "fullname": f"{stock['name']}股份有限公司",
                "enname": "",
                "cnspell": "",
                "market": stock.get("market", ""),
                "exchange": stock.get("exchange", ""),
                "curr_type": "CNY",
                "list_status": list_status,
                "list_date": "20100101",
                "delist_date": "",
                "is_hs": "N",
            }
            data.append(item)

        # 验证数据
        validated = StockBasicResponse(data=data)
        df = pd.DataFrame([item.model_dump() for item in validated.data])

        # 确保列顺序
        columns = [
            "ts_code",
            "symbol",
            "name",
            "area",
            "industry",
            "fullname",
            "enname",
            "cnspell",
            "market",
            "exchange",
            "curr_type",
            "list_status",
            "list_date",
            "delist_date",
            "is_hs",
        ]
        df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_fina_indicator(
        self, ts_code: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        """生成财务指标数据"""
        if not end_date:
            end_date = "20241231"

        if ts_code:
            stocks = [self._get_stock_info(ts_code)] if self._get_stock_info(ts_code) else []
        else:
            stocks = self.MOCK_STOCKS[:8]

        prompt = self._build_fina_indicator_prompt(stocks, end_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟财务指标数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_fina_indicator_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
                "ts_code",
                "ann_date",
                "end_date",
                "eps",
                "dt_eps",
                "total_revenue_ps",
                "revenue_ps",
                "capital_rese",
                "undist_profit",
                "extra_item",
                "profit_dedt",
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
                "valuechange_income",
                "interst_income",
                "daa_exp",
                "ebit",
                "ebitda",
                "fcff",
                "fcfe",
                "current_exint",
                "noncurrent_exint",
                "interestdebt",
                "netdebt",
                "tangible_asset",
                "working_capital",
                "networking_capital",
                "invest_capital",
                "retained_earnings",
                "diluted2_eps",
                "bps",
                "ocfps",
                "retainps",
                "cfps",
                "ebit_ps",
                "fcff_ps",
                "fcfe_ps",
                "netprofit_margin",
                "grossprofit_margin",
                "cogs_of_sales",
                "expense_of_sales",
                "profit_to_gr",
                "saleexp_to_gr",
                "adminexp_of_gr",
                "finaexp_of_gr",
                "exclexp_of_gr",
                "ocf_to_gr",
                "ocf_to_or",
                "q_sales_yoy",
                "q_op_qoq",
                "equity_yoy",
                "rd_exp",
            ]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_income(
        self, ts_code: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        """生成利润表数据"""
        if not end_date:
            end_date = "20241231"

        if ts_code:
            stocks = [self._get_stock_info(ts_code)] if self._get_stock_info(ts_code) else []
        else:
            stocks = self.MOCK_STOCKS[:6]

        prompt = self._build_income_prompt(stocks, end_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟利润表数据，确保利润核算关系合理。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_income_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
                "int_income",
                "prem_earned",
                "comm_income",
                "n_commis_income",
                "n_oi",
                "other_business_income",
                "total_cogs",
                "oper_cost",
                "int_exp",
                "comm_exp",
                "prem_refund",
                "compens_payout",
                "reser_insur_liab",
                "div_payt",
                "reins_exp",
                "oper_exp",
                "compens_payout_refu",
                "insur_reser_refu",
                "reins_cost_refund",
                "other_bus_cost",
                "operate_profit",
                "non_oper_income",
                "non_oper_exp",
                "nca_disploss",
                "total_profit",
                "income_tax",
                "n_income",
                "n_income_attr_p",
                "minority_gain",
                "oth_compr_income",
                "t_compr_income",
                "compr_inc_attr_p",
                "compr_inc_attr_m",
                "ebit",
                "ebitda",
                "insurance_exp",
                "undist_profit",
                "distable_profit",
            ]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_balance_sheet(
        self, ts_code: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        """生成资产负债表数据"""
        if not end_date:
            end_date = "20241231"

        if ts_code:
            stocks = [self._get_stock_info(ts_code)] if self._get_stock_info(ts_code) else []
        else:
            stocks = self.MOCK_STOCKS[:6]

        prompt = self._build_balance_sheet_prompt(stocks, end_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟资产负债表数据，确保会计等式关系：资产=负债+所有者权益。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_balance_sheet_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
                "div_receiv",
                "int_receiv",
                "inventories",
                "amor_exp",
                "nca_within_1y",
                "sett_rsrv",
                "loanto_oth_bank_fi",
                "premium_receiv",
                "reinsur_receiv",
                "reinsur_res_receiv",
                "pur_resale_fa",
                "oth_cur_assets",
                "total_cur_assets",
                "fa_avail_for_sale",
                "htm_invest",
                "lt_eqt_invest",
                "invest_real_estate",
                "time_deposits",
                "oth_assets",
                "lt_rec",
                "fix_assets",
                "cip",
                "const_materials",
                "fix_assets_disp",
                "produc_bio_assets",
                "oil_and_gas_assets",
                "intan_assets",
                "rd",
                "goodwill",
                "lt_amor_exp",
                "defer_tax_assets",
                "decr_in_disbur",
                "oth_nca",
                "total_nca",
                "cash_reser_cb",
                "depos_in_oth_bfi",
                "prec_metals",
                "deriv_assets",
                "dp_receiv",
                "total_assets",
                "lt_borr",
                "st_borr",
                "cb_borr",
                "depos_ib_deposits",
                "loan_oth_bank",
                "trading_fl",
                "notes_payable",
                "acct_payable",
                "adv_receipts",
                "sold_for_repur_fa",
                "comm_payable",
                "payroll_payable",
                "taxes_payable",
                "int_payable",
                "div_payable",
                "oth_payable",
                "acc_exp",
                "deferred_inc",
                "st_bonds_payable",
                "payable_to_reinsurer",
                "rsrv_insur_cont",
                "acting_trading_sec",
                "acting_uw_sec",
                "non_cur_liab_due_1y",
                "oth_cur_liab",
                "total_cur_liab",
                "lt_payable",
                "specific_payables",
                "estimated_liab",
                "defer_tax_liab",
                "defer_inc_non_cur_liab",
                "oth_ncl",
                "total_ncl",
                "depos_oth_bfi",
                "deriv_liab",
                "reserves",
                "undur_por_reserves",
                "money_cap_reser",
                "owed_invest",
                "oth_eqt_tools_p",
                "total_liab_eqt",
                "tot_liab_shrhldr_eqy",
                "cap_rese_ps",
                "cash_net_rase",
                "bfe_texpr",
                "saleexp_fix",
                "bddp",
                "dva_depr",
                "fin_exp_int_inc",
                "transfer_to_sundry",
                "total_profit",
                "profit_for_owner",
            ]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_cash_flow(
        self, ts_code: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        """生成现金流量表数据"""
        if not end_date:
            end_date = "20241231"

        if ts_code:
            stocks = [self._get_stock_info(ts_code)] if self._get_stock_info(ts_code) else []
        else:
            stocks = self.MOCK_STOCKS[:6]

        prompt = self._build_cash_flow_prompt(stocks, end_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟现金流量表数据，确保现金流量勾稽关系合理。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_cash_flow_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
                "n_depos_incr_fi",
                "n_incr_loans_cb",
                "n_inc_borr_oth_fi",
                "prem_fr_orig_contr",
                "n_incr_insured_dep",
                "n_reinsur_prem",
                "incr_illness_res",
                "n_incr_disp_tfa",
                "ifc_cash_incr",
                "n_incr_loans_oth_bank",
                "n_cap_incr_repur",
                "c_fr_oth_operate_a",
                "c_inf_fr_operate_a",
                "c_paid_goods_s",
                "c_paid_to_for_empl",
                "c_paid_for_taxes",
                "n_incr_clt_loan_adv",
                "n_incr_dep_cbob",
                "c_pay_claims_orig_inco",
                "pay_handling_chrg",
                "c_pay_all_tax",
                "c_paid_to_oth_operator_pur",
                "st_cash_out_act",
                "s_mjr_subsidiary_oth_bsn",
                "stot_cash_out_act",
                "n_cashflow_act",
                "oth_recp_ral_inv_act",
                "c_disp_withdrwl_invest",
                "c_recp_return_invest",
                "n_recp_disp_fiolta",
                "n_recp_disp_sobu",
                "stot_cash_inflow_inv_act",
                "c_pay_acq_const_fiolta",
                "c_paid_invest",
                "n_disp_subs_oth_biz",
                "oth_pay_ral_inv_act",
                "n_incr_pledge_loan",
                "stot_cash_outflow_inv_act",
                "n_cashflow_inv_act",
                "c_recp_borrow",
                "proc_issue_shares",
                "oth_recp_ral_fnc_act",
                "stot_cash_inflow_fnc_act",
                "c_prepay_debt",
                "c_pay_amount_borr_oth_fi",
                "c_pay_div_prof_int",
                "stot_cash_outflow_fnc_act",
                "n_cashflow_fnc_act",
                "eff_fx_flu_cash",
                "c_cash_equ_beg_period",
                "c_cash_equ_end_period",
                "c_recp_cap_contrib",
                "incl_dvd_profit_paid_sc_ms",
                "uncon_invest_loss",
                "prov_depr_assets",
                "depr_fa_coga_dpba",
                "amort_intang_assets",
                "lt_amort_deferred_exp",
                "decr_deferred_exp",
                "incr_acc_exp",
                "loss_disp_fiolta",
                "loss_scr_fa",
                "loss_fv_chg",
                "fin_exp",
                "invest_loss",
                "decr_deferred_inc_tax_assets",
                "incr_deferred_inc_tax_liab",
                "decr_inventories",
                "decr_oper_payable",
                "incr_oper_payable",
                "others",
                "im_net_cashflow_oper_act",
                "conv_debt_into_cap",
                "conv_copbonds_due_within_1y",
                "fa_fnc_leases",
                "end_bal_cash",
                "beg_bal_cash",
                "end_bal_cash_equ",
                "beg_bal_cash_equ",
            ]
            df = df[[col for col in columns if col in df.columns]]

            # 后处理：修正现金流量表勾稽关系
            required = [
                "c_cash_equ_beg_period",
                "n_cashflow_act",
                "n_cashflow_inv_act",
                "n_cashflow_fnc_act",
                "eff_fx_flu_cash",
                "c_cash_equ_end_period",
            ]
            if all(c in df.columns for c in required):
                df["c_cash_equ_end_period"] = (
                    pd.to_numeric(df["c_cash_equ_beg_period"], errors="coerce").fillna(0)
                    + pd.to_numeric(df["n_cashflow_act"], errors="coerce").fillna(0)
                    + pd.to_numeric(df["n_cashflow_inv_act"], errors="coerce").fillna(0)
                    + pd.to_numeric(df["n_cashflow_fnc_act"], errors="coerce").fillna(0)
                    + pd.to_numeric(df["eff_fx_flu_cash"], errors="coerce").fillna(0)
                )

        return df

    async def generate_money_flow(
        self, ts_code: str | None = None, trade_date: str | None = None
    ) -> pd.DataFrame:
        """生成个股资金流向数据"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        if ts_code:
            stocks = [self._get_stock_info(ts_code)] if self._get_stock_info(ts_code) else []
        else:
            stocks = self.MOCK_STOCKS[:8]

        prompt = self._build_money_flow_prompt(stocks, trade_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟资金流向数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_money_flow_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_top_list(self, trade_date: str | None = None) -> pd.DataFrame:
        """生成龙虎榜数据"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        prompt = self._build_top_list_prompt(trade_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟龙虎榜数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_top_list_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
                "brk_name",
                "brk_buy",
                "brk_sell",
            ]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_limit_list(
        self, trade_date: str | None = None, limit_type: str | None = None
    ) -> pd.DataFrame:
        """生成涨停榜数据"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        prompt = self._build_limit_list_prompt(trade_date, limit_type)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟涨停榜数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_limit_list_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
                "limit_status",
            ]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_margin(
        self, ts_code: str | None = None, trade_date: str | None = None
    ) -> pd.DataFrame:
        """生成融资融券数据"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        if ts_code:
            stocks = [self._get_stock_info(ts_code)] if self._get_stock_info(ts_code) else []
        else:
            stocks = self.MOCK_STOCKS[:8]

        prompt = self._build_margin_prompt(stocks, trade_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟融资融券数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_margin_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_money_flow_hsgt(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        """生成沪深港通资金流向数据"""
        if not start_date and not end_date:
            today = datetime.now().strftime("%Y%m%d")
            start_date = today
            end_date = today

        prompt = self._build_money_flow_hsgt_prompt(start_date, end_date)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟沪深港通资金流向数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_money_flow_hsgt_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_concept(self) -> pd.DataFrame:
        """生成概念股分类数据"""
        prompt = self._build_concept_prompt()

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟概念股分类数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_concept_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = ["code", "name", "src"]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_concept_detail(self, concept_name: str | None = None) -> pd.DataFrame:
        """生成概念股明细数据"""
        if not concept_name:
            concept_name = "人工智能"

        prompt = self._build_concept_detail_prompt(concept_name)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟概念股明细数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_concept_detail_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = ["id", "concept_name", "ts_code", "name", "in_date", "out_date"]
            df = df[[col for col in columns if col in df.columns]]

        return df

    async def generate_stock_company(self, ts_code: str | None = None) -> pd.DataFrame:
        """生成上市公司基本信息数据"""
        if ts_code:
            stocks = [self._get_stock_info(ts_code)] if self._get_stock_info(ts_code) else []
        else:
            stocks = self.MOCK_STOCKS[:8]

        prompt = self._build_stock_company_prompt(stocks)

        content = await self._call_llm_async(
            "你是一个专业的金融数据生成助手。请严格按照用户要求的JSON格式返回模拟上市公司基本信息数据。",
            prompt,
        )
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        validated_data = self._validate_stock_company_response(raw_data)

        df = pd.DataFrame(validated_data["data"])
        if not df.empty:
            columns = [
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
            df = df[[col for col in columns if col in df.columns]]

        return df

    def _build_daily_prompt(
        self,
        ts_code: str,
        stock_name: str,
        industry: str,
        start_date: str,
        end_date: str,
        base_price: float,
    ) -> str:
        """构建日K线数据生成prompt"""

        # 生成交易日列表（排除周末）
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        trade_dates = []
        current = start_dt
        while current <= end_dt:
            if current.weekday() < 5:  # 周一到周五
                trade_dates.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)

        trade_dates_str = ", ".join(trade_dates[:30])  # 最多显示30个交易日
        if len(trade_dates) > 30:
            trade_dates_str += f" ... (共{len(trade_dates)}个交易日)"

        return f"""请为股票 {ts_code} ({stock_name}) 生成日K线数据。

股票信息：
- 股票代码: {ts_code}
- 股票名称: {stock_name}
- 所属行业: {industry}
- 基准价格: 约 {base_price:.2f} 元（基于此价格生成合理波动）

时间范围：
- 开始日期: {start_date}
- 结束日期: {end_date}
- 交易日列表: {trade_dates_str}

数据生成要求：
1. 生成每个交易日的OHLC数据（开盘、最高、最低、收盘）
2. 价格走势应符合行业特征，保持合理波动
3. 开盘价、收盘价、最高价、最低价逻辑合理（high >= max(open,close,low), low <= min(open,close,high)）
4. 涨跌幅控制在 ±10%（科创板/创业板可放宽至 ±20%）
5. 成交量与价格波动相关，大盘股成交量大，小盘股成交量小
6. 保持时间连续性：相邻交易日的收盘价应接近
7. pre_close = 前一交易日的close，change = close - pre_close，pct_chg = change/pre_close * 100

重要约束：
- {ts_code} 的最后3位数字是 {ts_code[:6][-3:]}
- 基准价格为 {base_price:.2f} 元，生成的价格应围绕此基准波动
- 行业为 {industry}，请参考该行业的典型股价波动特征

返回格式（严格JSON）：
{{
    "data": [
        {{
            "ts_code": "{ts_code}",
            "trade_date": "YYYYMMDD",
            "open": 开盘价,
            "high": 最高价,
            "low": 最低价,
            "close": 收盘价,
            "pre_close": 昨收,
            "change": 涨跌额,
            "pct_chg": 涨跌幅,
            "vol": 成交量(手),
            "amount": 成交额(千元)
        }},
        ...
    ]
}}

生成 {len(trade_dates)} 条记录，覆盖上述所有交易日。"""

    def _build_daily_basic_prompt(self, stocks: list[dict[str, Any]], trade_date: str) -> str:
        """构建每日指标数据生成prompt"""

        stocks_info = "\n".join(
            [
                f"- {s['ts_code']} ({s['name']}, {s['industry']})"
                for s in stocks[:10]  # 最多显示10只股票
            ]
        )

        return f"""请为以下股票生成 {trade_date} 的每日指标数据。

股票列表：
{stocks_info}
{"" if len(stocks) <= 10 else f"... 共 {len(stocks)} 只股票"}

指标说明：
- close: 收盘价
- turnover_rate: 换手率(%)
- turnover_rate_f: 自由流通股换手率(%)
- volume_ratio: 量比
- pe: 市盈率
- pe_ttm: 滚动市盈率
- pb: 市净率
- ps: 市销率
- total_share: 总股本(万股)
- float_share: 流通股本(万股)
- total_mv: 总市值(万元)
- circ_mv: 流通市值(万元)

生成要求：
1. 不同行业的估值水平应合理（银行PE较低，科技股PE较高）
2. 市值计算：total_mv = close * total_share, circ_mv = close * float_share
3. 换手率通常在 0.5% - 20% 之间
4. 数据应具有合理性，避免极端值

返回格式（严格JSON）：
{{
    "data": [
        {{
            "ts_code": "股票代码",
            "trade_date": "{trade_date}",
            "close": 收盘价,
            "turnover_rate": 换手率,
            "turnover_rate_f": 自由流通股换手率,
            "volume_ratio": 量比,
            "pe": 市盈率,
            "pe_ttm": 滚动市盈率,
            "pb": 市净率,
            "ps": 市销率,
            "total_share": 总股本,
            "float_share": 流通股本,
            "total_mv": 总市值,
            "circ_mv": 流通市值
        }},
        ...
    ]
}}

生成 {len(stocks)} 条记录。"""

    def _build_fina_indicator_prompt(self, stocks: list[dict[str, Any]], end_date: str) -> str:
        """构建财务指标数据生成prompt"""

        stocks_info = "\n".join(
            [f"- {s['ts_code']} ({s['name']}, {s['industry']})" for s in stocks[:10]]
        )

        return f"""请为以下股票生成 {end_date} 报告期的财务指标数据。

股票列表：
{stocks_info}
{"" if len(stocks) <= 10 else f"... 共 {len(stocks)} 只股票"}

生成要求：
1. 指标应符合行业特征（银行关注资本充足率，制造业关注周转率，科技关注研发投入）
2. EPS、BPS等每股指标应与股本规模匹配
3. 盈利能力指标应在合理范围内（毛利率0-100%，净利率可能为负）
4. 同比数据应反映合理的增长或下滑趋势
5. 所有字段为数值型，缺失可用null

返回格式（严格JSON）：
{{
    "data": [
        {{
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "end_date": "{end_date}",
            "eps": 基本每股收益,
            "dt_eps": 稀释每股收益,
            "total_revenue_ps": 每股营业总收入,
            ... （其他所有字段）
        }},
        ...
    ]
}}

生成 {len(stocks)} 条记录，每条记录包含完整的财务指标字段。"""

    def _build_income_prompt(self, stocks: list[dict[str, Any]], end_date: str) -> str:
        """构建利润表数据生成prompt"""

        stocks_info = "\n".join(
            [f"- {s['ts_code']} ({s['name']}, {s['industry']})" for s in stocks[:10]]
        )

        return f"""请为以下股票生成 {end_date} 报告期的利润表数据。

股票列表：
{stocks_info}
{"" if len(stocks) <= 10 else f"... 共 {len(stocks)} 只股票"}

生成要求：
1. 收入规模应符合行业特征（银行利息收入为主，制造业营业收入为主）
2. 利润核算关系应基本合理：营业利润 ≈ 营业收入 - 营业成本 - 费用
3. 净利润 = 利润总额 - 所得税
4. 数据单位保持统一（万元人民币）
5. 所有字段为数值型，缺失可用null

返回格式（严格JSON）：
{{
    "data": [
        {{
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "f_ann_date": "首次公告日期YYYYMMDD",
            "end_date": "{end_date}",
            "report_type": "报告类型(如1年报/2季报等)",
            "comp_type": "1",
            "basic_eps": 基本每股收益,
            "diluted_eps": 稀释每股收益,
            "total_revenue": 营业总收入,
            "revenue": 营业收入,
            "int_income": 利息收入,
            "prem_earned": 已赚保费,
            "comm_income": 手续费及佣金收入,
            "n_oth_business_income": 其他业务收入,
            "n_oth_income": 其他收益,
            "total_cogs": 营业总成本,
            "oper_cost": 营业成本,
            "int_exp": 利息支出,
            "comm_exp": 手续费及佣金支出,
            "biz_tax_surchg": 营业税金及附加,
            "sell_exp": 销售费用,
            "admin_exp": 管理费用,
            "fin_exp": 财务费用,
            "assets_impair_loss": 资产减值损失,
            "prem_refund": 退保金,
            "compens_payout": 赔付支出,
            "reser_insur_liab": 提取保险责任准备金,
            "div_payt": 保单红利支出,
            "reinsur_exp": 分保费用,
            "oper_exp": 营业支出,
            "compens_payout_refu": 减:摊回赔付支出,
            "insur_reser_refu": 减:摊回保险责任准备金,
            "reinsur_cost_refund": 减:摊回分保费用,
            "other_bus_cost": 其他业务成本,
            "operate_profit": 营业利润,
            "non_oper_income": 营业外收入,
            "non_oper_exp": 营业外支出,
            "nca_disploss": 其中:减:非流动资产处置损失,
            "total_profit": 利润总额,
            "income_tax": 所得税费用,
            "n_income": 净利润,
            "n_income_attr_p": 归属于母公司所有者的净利润,
            "minority_gain": 少数股东损益,
            "oth_compr_income": 其他综合收益,
            "t_compr_income": 综合收益总额,
            "compr_inc_attr_p": 归属于母公司所有者的综合收益总额,
            "compr_inc_attr_m_s": 归属于少数股东的综合收益总额,
            "ebit": 息税前利润,
            "ebitda": 息税折旧摊销前利润,
            "insurance_exp": 保险业务支出,
            "undist_profit": 年初未分配利润,
            "distable_profit": 可分配利润,
            "rd_exp": 研发费用,
            "fin_exp_int_inc": 财务费用_利息收入,
            "grossprofit": 毛利,
            "income_before_tax": 税前利润,
            "non_oper_income_net": 营业外收支净额,
            "credit_impair_loss": 信用减值损失,
            "fair_value_chg_income": 公允价值变动收益,
            "invest_income": 投资收益,
            "asset_disposal_income": 资产处置收益,
            "forex_gain": 汇兑收益,
            "oth_income": 其他收益,
            "net_profit": 扣非净利润,
            "going_concern_net_profit": 持续经营净利润,
            "quit_concern_net_profit": 终止经营净利润
        }},
        ...
    ]
}}

生成 {len(stocks)} 条记录。"""

    def _build_balance_sheet_prompt(self, stocks: list[dict[str, Any]], end_date: str) -> str:
        """构建资产负债表数据生成prompt"""

        stocks_info = "\n".join(
            [f"- {s['ts_code']} ({s['name']}, {s['industry']})" for s in stocks[:10]]
        )

        return f"""请为以下股票生成 {end_date} 报告期的资产负债表数据。

股票列表：
{stocks_info}
{"" if len(stocks) <= 10 else f"... 共 {len(stocks)} 只股票"}

生成要求：
1. 资产负债结构应符合行业特征（银行高负债，制造业有存货和固定资产，科技公司轻资产）
2. 严格遵循会计等式：总资产 = 总负债 + 所有者权益
3. 流动资产 + 非流动资产 = 总资产
4. 流动负债 + 非流动负债 ≈ 总负债
5. 数据单位保持统一（万元人民币）
6. 所有字段为数值型，缺失可用null
7. 必须包含 total_assets 和 total_liab_eqt 字段，并确保 total_assets ≈ total_liab_eqt

返回格式（严格JSON）：
{{
    "data": [
        {{
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "f_ann_date": "首次公告日期YYYYMMDD",
            "end_date": "{end_date}",
            "report_type": "报告类型",
            "comp_type": "1",
            "total_share": 总股本,
            "cap_rese": 资本公积金,
            "undistr_porfit": 未分配利润,
            "surplus_rese": 盈余公积金,
            "special_rese": 专项储备,
            "money_cap": 货币资金,
            "trad_asset": 交易性金融资产,
            "notes_receiv": 应收票据,
            "accounts_receiv": 应收账款,
            "oth_receiv": 其他应收款,
            "prepayment": 预付款项,
            "div_receiv": 应收股利,
            "int_receiv": 应收利息,
            "inventories": 存货,
            "amor_exp": 长期待摊费用,
            "nca_within_1y": 一年内到期的非流动资产,
            "sett_rsrv": 结算备付金,
            "loanto_oth_bank_fi": 拆出资金,
            "premium_receiv": 应收保费,
            "reinsur_receiv": 应收分保账款,
            "reinsur_res_receiv": 应收分保合同准备金,
            "pur_resale_fa": 买入返售金融资产,
            "oth_cur_assets": 其他流动资产,
            "total_cur_assets": 流动资产合计,
            "fa_avail_for_sale": 可供出售金融资产,
            "htm_invest": 持有至到期投资,
            "lt_eqt_invest": 长期股权投资,
            "invest_real_estate": 投资性房地产,
            "time_deposits": 定期存款,
            "oth_assets": 其他资产,
            "lt_rec": 长期应收款,
            "fix_assets": 固定资产,
            "cip": 在建工程,
            "const_materials": 工程物资,
            "fix_assets_disp": 固定资产清理,
            "produc_bio_assets": 生产性生物资产,
            "oil_and_gas_assets": 油气资产,
            "intan_assets": 无形资产,
            "rd": 研发支出,
            "goodwill": 商誉,
            "lt_amor_exp": 长期待摊费用,
            "defer_tax_assets": 递延所得税资产,
            "decr_in_disbur": 发放贷款及垫款,
            "oth_nca": 其他非流动资产,
            "total_nca": 非流动资产合计,
            "cash_reser_cb": 货币资金_银行,
            "depos_in_oth_bfi": 存放同业款项,
            "prec_metals": 贵金属,
            "deriv_assets": 衍生金融资产,
            "dp_receiv": 应收款项融资,
            "total_assets": 资产总计,
            "lt_borr": 长期借款,
            "st_borr": 短期借款,
            "cb_borr": 向中央银行借款,
            "depos_ib_deposits": 吸收存款及同业存放,
            "loan_oth_bank": 拆入资金,
            "trading_fl": 交易性金融负债,
            "notes_payable": 应付票据,
            "acct_payable": 应付账款,
            "adv_receipts": 预收款项,
            "sold_for_repur_fa": 卖出回购金融资产款,
            "comm_payable": 应付手续费及佣金,
            "payroll_payable": 应付职工薪酬,
            "taxes_payable": 应交税费,
            "int_payable": 应付利息,
            "div_payable": 应付股利,
            "oth_payable": 其他应付款,
            "acc_exp": 预提费用,
            "deferred_inc": 递延收益,
            "st_bonds_payable": 应付短期债券,
            "payable_to_reinsurer": 应付分保账款,
            "rsrv_insur_cont": 保险合同准备金,
            "acting_trading_sec": 代理买卖证券款,
            "acting_uw_sec": 代理承销证券款,
            "non_cur_liab_due_1y": 一年内到期的非流动负债,
            "oth_cur_liab": 其他流动负债,
            "total_cur_liab": 流动负债合计,
            "lt_payable": 长期应付款,
            "specific_payables": 专项应付款,
            "estimated_liab": 预计负债,
            "defer_tax_liab": 递延所得税负债,
            "defer_inc_non_cur_liab": 递延收益_非流动负债,
            "oth_ncl": 其他非流动负债,
            "total_ncl": 非流动负债合计,
            "depos_oth_bfi": 同业及其他金融机构存放款项,
            "deriv_liab": 衍生金融负债,
            "reserves": 储备金,
            "undur_por_reserves": 未分配利润储备,
            "money_cap_reser": 货币资金储备,
            "owed_invest": 少数股东投资,
            "oth_eqt_tools_p": 其他权益工具_优先股,
            "total_liab_eqt": 负债及所有者权益总计,
            "tot_liab_shrhldr_eqy": 负债及股东权益总计,
            "cap_rese_ps": 每股资本公积金,
            "cash_net_rase": 现金净增加额,
            "bfe_texpr": 前期差错更正,
            "saleexp_fix": 销售费用调整,
            "bddp": 坏账准备,
            "dva_depr": 折旧与摊销,
            "fin_exp_int_inc": 财务费用_利息收入,
            "transfer_to_sundry": 转入其他,
            "total_profit": 利润总额,
            "profit_for_owner": 归属于母公司所有者的净利润
        }},
        ...
    ]
}}

生成 {len(stocks)} 条记录。"""

    def _build_cash_flow_prompt(self, stocks: list[dict[str, Any]], end_date: str) -> str:
        """构建现金流量表数据生成prompt"""

        stocks_info = "\n".join(
            [f"- {s['ts_code']} ({s['name']}, {s['industry']})" for s in stocks[:10]]
        )

        return f"""请为以下股票生成 {end_date} 报告期的现金流量表数据。

股票列表：
{stocks_info}
{"" if len(stocks) <= 10 else f"... 共 {len(stocks)} 只股票"}

生成要求：
1. 现金流结构应符合行业特征（经营现金流为正，投资现金流可能为负，筹资现金流视融资情况而定）
2. 现金流量勾稽关系合理：现金及现金等价物净增加额 ≈ 经营活动现金流 + 投资活动现金流 + 筹资活动现金流 + 汇率影响
3. 期末现金 ≈ 期初现金 + 净增加额
4. 数据单位保持统一（万元人民币）
5. 所有字段为数值型，缺失可用null
6. 必须包含 n_cashflow_act, n_cashflow_inv_act, n_cashflow_fnc_act, eff_fx_flu_cash, c_cash_equ_beg_period, c_cash_equ_end_period 这六个关键字段，并确保勾稽关系：期末现金 ≈ 期初现金 + 经营现金流 + 投资现金流 + 筹资现金流 + 汇率影响

返回格式（严格JSON）：
{{
    "data": [
        {{
            "ts_code": "股票代码",
            "ann_date": "公告日期YYYYMMDD",
            "f_ann_date": "首次公告日期YYYYMMDD",
            "end_date": "{end_date}",
            "comp_type": "1",
            "report_type": "报告类型",
            "net_profit": 净利润,
            "finan_exp": 财务费用,
            "c_fr_sale_sg": 销售商品提供劳务收到的现金,
            "recp_tax_rends": 收到的税费返还,
            "n_depos_incr_fi": 客户存款和同业存放款项净增加额,
            "n_incr_loans_cb": 向中央银行借款净增加额,
            "n_inc_borr_oth_fi": 向其他金融机构拆入资金净增加额,
            "prem_fr_orig_contr": 收到原保险合同保费取得的现金,
            "n_incr_insured_dep": 保户储金及投资款净增加额,
            "n_reinsur_prem": 处置以公允价值计量且其变动计入当期损益的金融资产净增加额,
            "incr_illness_res": 收取利息和手续费净增加额,
            "n_incr_disp_tfa": 拆入资金净增加额,
            "ifc_cash_incr": 回购业务资金净增加额,
            "n_incr_loans_oth_bank": 客户贷款及垫款净增加额,
            "n_cap_incr_repur": 存放中央银行和同业款项净增加额,
            "c_fr_oth_operate_a": 收到其他与经营活动有关的现金,
            "c_inf_fr_operate_a": 经营活动现金流入小计,
            "c_paid_goods_s": 购买商品接受劳务支付的现金,
            "c_paid_to_for_empl": 支付给职工以及为职工支付的现金,
            "c_paid_for_taxes": 支付的各项税费,
            "n_incr_clt_loan_adv": 支付其他与经营活动有关的现金,
            "n_incr_dep_cbob": 经营活动现金流出小计,
            "c_pay_claims_orig_inco": 经营活动产生的现金流量净额,
            "pay_handling_chrg": 收回投资收到的现金,
            "c_pay_all_tax": 取得投资收益收到的现金,
            "c_paid_to_oth_operator_pur": 处置固定资产无形资产和其他长期资产收回的现金,
            "st_cash_out_act": 投资活动现金流入小计,
            "s_mjr_subsidiary_oth_bsn": 购建固定资产无形资产和其他长期资产支付的现金,
            "stot_cash_out_act": 投资活动现金流出小计,
            "n_cashflow_act": 投资活动产生的现金流量净额,
            "oth_recp_ral_inv_act": 吸收投资收到的现金,
            "c_disp_withdrwl_invest": 取得借款收到的现金,
            "c_recp_return_invest": 发行债券收到的现金,
            "n_recp_disp_fiolta": 收到其他与筹资活动有关的现金,
            "n_recp_disp_sobu": 筹资活动现金流入小计,
            "stot_cash_inflow_inv_act": 偿还债务支付的现金,
            "c_pay_acq_const_fiolta": 分配股利利润或偿付利息支付的现金,
            "c_paid_invest": 支付其他与筹资活动有关的现金,
            "n_disp_subs_oth_biz": 筹资活动现金流出小计,
            "oth_pay_ral_inv_act": 筹资活动产生的现金流量净额,
            "n_incr_pledge_loan": 汇率变动对现金及现金等价物的影响,
            "stot_cash_outflow_inv_act": 现金及现金等价物净增加额,
            "n_cashflow_inv_act": 期末现金及现金等价物余额,
            "c_recp_borrow": 期初现金及现金等价物余额,
            "proc_issue_shares": 将净利润调节为经营活动现金流量,
            "oth_recp_ral_fnc_act": 不涉及现金收支的重大投资和筹资活动,
            "stot_cash_inflow_fnc_act": 现金及现金等价物净变动情况,
            "c_prepay_debt": 债务转为资本,
            "c_pay_amount_borr_oth_fi": 一年内到期的可转换公司债券,
            "c_pay_div_prof_int": 融资租入固定资产,
            "stot_cash_outflow_fnc_act": 现金的期末余额,
            "n_cashflow_fnc_act": 现金的期初余额,
            "eff_fx_flu_cash": 现金等价物的期末余额,
            "c_cash_equ_beg_period": 现金等价物的期初余额,
            "c_cash_equ_end_period": 现金及现金等价物的期末余额,
            "c_recp_cap_contrib": 接收资本贡献收到的现金,
            "incl_dvd_profit_paid_sc_ms": 少数股东损益,
            "uncon_invest_loss": 未确认投资损失,
            "prov_depr_assets": 资产减值准备,
            "depr_fa_coga_dpba": 固定资产折旧油气资产折耗生产性生物资产折旧,
            "amort_intang_assets": 无形资产摊销,
            "lt_amort_deferred_exp": 长期待摊费用摊销,
            "decr_deferred_exp": 待摊费用减少,
            "incr_acc_exp": 预提费用增加,
            "loss_disp_fiolta": 处置固定资产无形资产和其他长期资产的损失,
            "loss_scr_fa": 固定资产报废损失,
            "loss_fv_chg": 公允价值变动损失,
            "fin_exp": 财务费用_调节项,
            "invest_loss": 投资损失,
            "decr_deferred_inc_tax_assets": 递延所得税资产减少,
            "incr_deferred_inc_tax_liab": 递延所得税负债增加,
            "decr_inventories": 存货的减少,
            "decr_oper_payable": 经营性应收项目的减少,
            "incr_oper_payable": 经营性应付项目的增加,
            "others": 其他_调节项,
            "im_net_cashflow_oper_act": 经营活动现金流量净额_间接法,
            "conv_debt_into_cap": 债务转为资本,
            "conv_copbonds_due_within_1y": 一年内到期的可转换公司债券,
            "fa_fnc_leases": 融资租入固定资产,
            "end_bal_cash": 现金的期末余额,
            "beg_bal_cash": 现金的期初余额,
            "end_bal_cash_equ": 现金等价物的期末余额,
            "beg_bal_cash_equ": 现金等价物的期初余额
        }},
        ...
    ]
}}

生成 {len(stocks)} 条记录。"""

    def _build_money_flow_prompt(self, stocks: list[dict[str, Any]], trade_date: str) -> str:
        """构建个股资金流向数据生成prompt"""

        stocks_info = "\n".join(
            [f"- {s['ts_code']} ({s['name']}, {s['industry']})" for s in stocks[:10]]
        )

        return f"""请为以下股票生成 {trade_date} 的个股资金流向数据。

股票列表：
{stocks_info}
{"" if len(stocks) <= 10 else f"... 共 {len(stocks)} 只股票"}

生成要求：
1. 资金流向应符合股价走势（大涨时净流入为主，大跌时净流出为主）
2. 各类资金流向关系：净主力 = 大单+特大单买入 - 大单+特大单卖出
3. net_mf_vol ≈ 各类买卖成交量的净额
4. net_mf_amount ≈ 各类买卖成交金额的净额
5. 数据量级应与股票市值匹配

返回格式（严格JSON）：
{{
    "data": [
        {{
            "ts_code": "股票代码",
            "trade_date": "{trade_date}",
            "buy_sm_vol": 小单买入量,
            "buy_sm_amount": 小单买入金额,
            "sell_sm_vol": 小单卖出量,
            "sell_sm_amount": 小单卖出金额,
            "buy_md_vol": 中单买入量,
            "buy_md_amount": 中单买入金额,
            "sell_md_vol": 中单卖出量,
            "sell_md_amount": 中单卖出金额,
            "buy_lg_vol": 大单买入量,
            "buy_lg_amount": 大单买入金额,
            "sell_lg_vol": 大单卖出量,
            "sell_lg_amount": 大单卖出金额,
            "buy_elg_vol": 特大单买入量,
            "buy_elg_amount": 特大单买入金额,
            "sell_elg_vol": 特大单卖出量,
            "sell_elg_amount": 特大单卖出金额,
            "net_mf_vol": 净流入量,
            "net_mf_amount": 净流入金额,
            "trade_count": 交易笔数
        }},
        ...
    ]
}}

生成 {len(stocks)} 条记录。"""

    def _build_top_list_prompt(self, trade_date: str) -> str:
        """构建龙虎榜数据生成prompt"""

        return f"""请生成 {trade_date} 的龙虎榜数据。

生成要求：
1. 从预设股票池中选择5-10只股票生成龙虎榜记录
2. 选取当日涨跌幅较大（涨停或接近涨停）的股票
3. 营业部名称使用国内知名券商营业部（如：华泰证券、中信证券、国泰君安等）
4. 龙虎榜金额通常在数百万元到数亿元之间
5. net_amount = l_buy - l_sell

返回格式（严格JSON）：
{{
    "data": [
        {{
            "trade_date": "{trade_date}",
            "ts_code": "股票代码",
            "name": "股票名称",
            "close": 收盘价,
            "pct_chg": 涨跌幅,
            "turnover_rate": 换手率,
            "amount": 成交额,
            "l_buy": 龙虎榜买入金额,
            "l_sell": 龙虎榜卖出金额,
            "net_amount": 净额,
            "net_rate": 净买率,
            "amount_rate": 龙虎榜成交额占比,
            "reason": "上榜原因",
            "brk_name": "营业部名称",
            "brk_buy": 营业部买入金额,
            "brk_sell": 营业部卖出金额
        }},
        ...
    ]
}}

生成 6-10 条记录，覆盖不同的上榜股票和营业部。"""

    def _build_limit_list_prompt(self, trade_date: str, limit_type: str | None = None) -> str:
        """构建涨停榜数据生成prompt"""

        limit_type_desc = ""
        if limit_type:
            limit_type_desc = f" limit_type 要求: '{limit_type}'"

        return f"""请生成 {trade_date} 的涨停榜数据。{limit_type_desc}

生成要求：
1. 从预设股票池中选择5-10只涨停股票
2. 涨停股票的pct_chg应接近10%（沪深主板）或20%（创业板/科创板）
3. 封单金额(fd_amount)通常在数千万到数亿元
4. 首次涨停时间应在开盘后不久（如09:30-10:30）
5. 打开次数(open_times)反映涨停板是否松动
6. limit_type区分U型涨停（U）、一字涨停（T）等
7. 生成 5-10 条涨停或跌停记录。若 limit_type 为 'U' 只生成涨停，若为 'D' 只生成跌停，否则两者都生成。

返回格式（严格JSON）：
{{
    "data": [
        {{
            "trade_date": "YYYYMMDD",
            "ts_code": "股票代码",
            "name": "股票名称",
            "industry": "行业",
            "close": 收盘价,
            "pct_chg": 涨跌幅,
            "amount": 成交额,
            "limit_amount": 涨停金额,
            "float_mv": 流通市值,
            "total_mv": 总市值,
            "turnover_ratio": 换手率,
            "fd_amount": 封单金额,
            "first_time": "09:30:00",
            "last_time": "15:00:00",
            "open_times": 0,
            "up_stat": "U/D",
            "limit_type": "U/D",
            "limit_status": 1
        }},
        ...
    ]
}}

生成 6-10 条记录。"""

    def _build_margin_prompt(self, stocks: list[dict[str, Any]], trade_date: str) -> str:
        """构建融资融券数据生成prompt"""

        stocks_info = "\n".join(
            [f"- {s['ts_code']} ({s['name']}, {s['industry']})" for s in stocks[:10]]
        )

        return f"""请为以下股票生成 {trade_date} 的融资融券数据。

股票列表：
{stocks_info}
{"" if len(stocks) <= 10 else f"... 共 {len(stocks)} 只股票"}

生成要求：
1. 融资余额(rzye)和融券余量(rqyl)应为合理正数
2. 融资买入额(rzmre)、融资偿还额(rzche)与融资余额变动关系合理：当日融资余额 ≈ 前日融资余额 + 融资买入额 - 融资偿还额
3. 融券卖出量(rqchl)、融券偿还量(rqmcl)与融券余量变动关系合理
4. 融资融券余额(rzrqye) = 融资余额 + 融券余额
5. 数据量级应与股票市值和流动性匹配

返回格式（严格JSON）：
{{
    "data": [
        {{
            "trade_date": "{trade_date}",
            "ts_code": "股票代码",
            "rzye": 融资余额,
            "rqyl": 融券余量,
            "rzmre": 融资买入额,
            "rqylc": 融券余量金额,
            "rzche": 融资偿还额,
            "rqchl": 融券卖出量,
            "rqmcl": 融券偿还量,
            "szrje": 融资净买入,
            "xzrje": 新增加融资,
            "szrkje": 融资净偿还,
            "xzrkje": 新增加融券,
            "rzrqye": 融资融券余额,
            "rzrqylc": 融资融券余量
        }},
        ...
    ]
}}

生成 {len(stocks)} 条记录。"""

    def _build_money_flow_hsgt_prompt(self, start_date: str, end_date: str) -> str:
        """构建沪深港通资金流向数据生成prompt"""

        return f"""请生成 {start_date} 至 {end_date} 的沪深港通资金流向数据。

生成要求：
1. 北向资金(north_money) = 沪股通(hgt_cgtes) + 深股通(sgt_cgtes)
2. 南向资金(south_money) = 港股通(沪)(ggt_ss) + 港股通(深)(ggt_sz)
3. 持股数据(hgt_ltg, sgt_ltg)应为合理正数（万股级别）
4. 资金流向可正可负，反映当日外资流入流出情况
5. 数据应与A股市场近期表现保持一致的趋势
6. 生成每一天的数据记录，确保 north_money ≈ hgt_ltg + sgt_ltg

返回格式（严格JSON）：
{{
    "data": [
        {{
            "trade_date": "YYYYMMDD",
            "ggt_ss": 港股通(沪)净买入,
            "ggt_sz": 港股通(深)净买入,
            "hgt_ltg": 沪股通净流入,
            "hgt_cgtes": 沪股通持股数量,
            "hgt_cgtes_l": 沪股通持股数量变动,
            "sgt_ltg": 深股通净流入,
            "sgt_cgtes": 深股通持股数量,
            "sgt_cgtes_l": 深股通持股数量变动,
            "north_money": 北向资金净流入,
            "south_money": 南向资金净流入
        }},
        ...
    ]
}}

生成每一天的数据记录。"""

    def _build_concept_prompt(self) -> str:
        """构建概念股分类数据生成prompt"""

        return """请生成A股市场常见概念股分类数据。

生成要求：
1. 概念应具有代表性，覆盖当前市场热点（人工智能、新能源、半导体、医药等）
2. code使用字母数字组合，name为中文概念名称
3. src可为null或注明数据来源

返回格式（严格JSON）：
{
    "data": [
        {
            "code": "概念代码",
            "name": "概念名称",
            "src": "来源"
        },
        ...
    ]
}

生成 8-12 条记录。"""

    def _build_concept_detail_prompt(self, concept_name: str) -> str:
        """构建概念股明细数据生成prompt"""

        return f"""请生成"{concept_name}"概念股的明细数据。

生成要求：
1. 从预设股票池中选取属于该概念的5-10只股票
2. id可使用自增编号或股票代码+概念名组合
3. in_date为股票纳入该概念的日期（YYYYMMDD格式），out_date为调出日期（未调出则为null）
4. 名称(name)应与股票名称一致

返回格式（严格JSON）：
{{
    "data": [
        {{
            "id": "唯一标识",
            "concept_name": "{concept_name}",
            "ts_code": "股票代码",
            "name": "股票名称",
            "in_date": "纳入日期YYYYMMDD",
            "out_date": null
        }},
        ...
    ]
}}

生成 5-10 条记录。"""

    def _build_stock_company_prompt(self, stocks: list[dict[str, Any]]) -> str:
        """构建上市公司基本信息数据生成prompt"""

        stocks_info = "\n".join(
            [f"- {s['ts_code']} ({s['name']}, {s['industry']}, {s['area']})" for s in stocks[:10]]
        )

        return f"""请为以下公司生成上市公司基本信息。

公司列表：
{stocks_info}
{"" if len(stocks) <= 10 else f"... 共 {len(stocks)} 家公司"}

生成要求：
1. 董事长、总经理、董秘姓名以中文常见姓名为主
2. 注册资本(reg_capital)单位为万元，应符合行业公司规模
3. 成立日期(setup_date)为YYYYMMDD格式，上市时间应晚于成立时间
4.  province/city 应与股票信息中的地区一致
5. introduction为公司简介，200-500字
6. website为以http://或https://开头的公司官网
7. email为公司公开的官方邮箱
8. office为公司总部办公地址
9. employees为员工人数（人），应符合公司规模
10. main_business为主营业务描述
11. business_scope为营业执照上的经营范围

返回格式（严格JSON）：
{{
    "data": [
        {{
            "ts_code": "股票代码",
            "exchange": "交易所(SSE/SZE)",
            "chairman": "董事长姓名",
            "manager": "总经理姓名",
            "secretary": "董秘姓名",
            "reg_capital": 注册资本,
            "setup_date": "成立日期YYYYMMDD",
            "province": "省份",
            "city": "城市",
            "introduction": "公司简介",
            "website": "官网",
            "email": "邮箱",
            "office": "办公地址",
            "employees": 员工人数,
            "main_business": "主营业务",
            "business_scope": "经营范围"
        }},
        ...
    ]
}}

生成 {len(stocks)} 条记录。"""

    def _validate_daily_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证日K线数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")

        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")

        items = raw_data["data"]
        if not isinstance(items, list):
            raise ValueError(f"data必须是数组，实际为: {type(items).__name__}")

        if len(items) == 0:
            raise ValueError("data为空数组")

        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = DailyDataItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")

        return {"data": validated_items}

    def _validate_daily_basic_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证每日指标数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")

        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")

        items = raw_data["data"]
        if not isinstance(items, list):
            raise ValueError(f"data必须是数组，实际为: {type(items).__name__}")

        if len(items) == 0:
            raise ValueError("data为空数组")

        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = DailyBasicItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")

        return {"data": validated_items}

    def _validate_fina_indicator_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证财务指标数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = FinaIndicatorItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_income_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证利润表数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = IncomeItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_balance_sheet_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证资产负债表数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = BalanceSheetItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_cash_flow_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证现金流量表数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = CashFlowItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_money_flow_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证个股资金流向数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = MoneyFlowItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_top_list_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证龙虎榜数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = TopListItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_limit_list_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证涨停榜数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = LimitListItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_margin_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证融资融券数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = MarginItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_money_flow_hsgt_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证沪深港通资金流向数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = MoneyFlowHsgtItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_concept_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证概念股分类数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = ConceptItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_concept_detail_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证概念股明细数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = ConceptDetailItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    def _validate_stock_company_response(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """验证上市公司基本信息数据响应"""
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")
        if "data" not in raw_data:
            raise ValueError(f"LLM返回缺少data字段，实际字段: {list(raw_data.keys())}")
        items = raw_data["data"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("data必须是非空数组")
        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = StockCompanyItem(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条记录校验失败: {str(e)}")
        return {"data": validated_items}

    async def generate_cashflow(self, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        """Mock 现金流量表(4 季)。"""
        rows = [
            {
                "ts_code": ts_code,
                "end_date": ed,
                "n_cashflow_act": 5e8 - i * 2e7,  # 经营性现金流(故意递减,触发 yellow)
                "n_cashflow_inv_act": -2e8,
                "n_cash_flows_fnc_act": 1e8,
            }
            for i, ed in enumerate(["20240331", "20240630", "20240930", "20241231"])
        ]
        return pd.DataFrame(rows)

    async def generate_stk_holdernumber(
        self, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        """Mock 股东户数。"""
        rows = [
            {
                "ts_code": ts_code,
                "end_date": ed,
                "holder_num": 100000 - i * 5000,
            }
            for i, ed in enumerate(["20240331", "20240630", "20240930", "20241231"])
        ]
        return pd.DataFrame(rows)

    async def generate_disclosure_date(
        self, ts_code: str | None = None, start: str = "", end: str = ""
    ) -> pd.DataFrame:
        """Mock 披露日历(空 → 不触发事件)。"""
        return pd.DataFrame(columns=["ts_code", "ann_date", "end_date", "type"])

    async def generate_anns(self, ts_code: str, start: str = "", end: str = "") -> pd.DataFrame:
        """Mock 公告(简化:返回 1 条普通公告)。"""
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "ann_date": "20240501",
                    "title": "关于 2023 年度股东大会决议公告",
                    "content": "审议通过年度报告。",
                    "url": "https://example.com/ann/1",
                }
            ]
        )
