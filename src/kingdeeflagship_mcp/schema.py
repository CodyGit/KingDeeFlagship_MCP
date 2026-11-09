# -*- coding: utf-8 -*-
"""金蝶 KIS 旗舰版 / K3 系账套 业务对象（实体）字典。

说明
----
* KIS 旗舰版基于 KIS BOS 平台，数据落在 SQL Server，表结构与 K/3 WISE 高度同源，
  因此本字典同时适用于 KIS 旗舰版、KIS 专业版(12.x+)、K/3 WISE。
* 不同小版本字段会有增删，凡是标注 ``proven="likely"`` 的实体，建议先用
  ``kis discover --check-tables`` 在本机账套上校验一次；不存在会自动跳过。
* 实体既可用于「ADODB 只读查询」（连接串来自 COM 登录），也可作为 COM 业务组件调用的参数字典 key。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Entity:
    key: str                       # 实体编码（对外调用用这个）
    label: str                     # 中文名
    module: str                    # 业务模块
    table: str                     # 主表 / 视图
    pk: str = "FInterID"           # 主表主键
    entry_table: Optional[str] = None   # 分录表
    entry_link: str = "FInterID"        # 分录表关联主表的字段
    entry_pk: Optional[str] = None      # 分录表主键
    select_fields: str = "*"       # 默认返回字段
    fixed_where: Optional[str] = None   # 固定过滤（如单据类型 FTranType）
    date_field: Optional[str] = None    # 业务日期字段（支持 start_date/end_date）
    search_fields: Tuple[str, ...] = () # keyword 模糊检索字段
    code_field: Optional[str] = None    # 编码字段
    name_field: Optional[str] = None    # 名称字段
    default_order: Optional[str] = None
    proven: str = "confirmed"      # confirmed=常用确认；likely=版本差异需校验
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "module": self.module,
            "table": self.table,
            "pk": self.pk,
            "entry_table": self.entry_table,
            "entry_link": self.entry_link,
            "select_fields": self.select_fields,
            "fixed_where": self.fixed_where,
            "date_field": self.date_field,
            "search_fields": list(self.search_fields),
            "code_field": self.code_field,
            "name_field": self.name_field,
            "default_order": self.default_order,
            "proven": self.proven,
            "note": self.note,
        }


def _e(*args, **kwargs) -> Entity:
    return Entity(*args, **kwargs)


# ---------------------------------------------------------------- 基础资料
BASE_ENTITIES: List[Entity] = [
    _e("account", "会计科目", "base", "t_Account", pk="FAccountID",
       select_fields="FAccountID, FNumber, FName, FFullNumber, FParentID, FLevel, FDetail, "
                     "FGroupID, FDC, FIsCash, FIsBank, FQuantity, FAccountTypeID",
       search_fields=("FNumber", "FName", "FFullNumber"), code_field="FNumber", name_field="FName",
       default_order="FNumber"),
    _e("account_group", "科目类别", "base", "t_AccountGroup", pk="FGroupID",
       search_fields=("FNumber", "FName"), default_order="FNumber", proven="likely"),
    _e("customer", "客户", "base", "t_Organization", pk="FItemID",
       search_fields=("FNumber", "FName", "FShortName"), code_field="FNumber", name_field="FName",
       default_order="FNumber", note="客户主表；与 t_Item(FItemClassID=1) 通过 FItemID 关联"),
    _e("supplier", "供应商", "base", "t_Supplier", pk="FItemID",
       search_fields=("FNumber", "FName", "FShortName"), code_field="FNumber", name_field="FName",
       default_order="FNumber", note="与 t_Item(FItemClassID=8) 通过 FItemID 关联"),
    _e("department", "部门", "base", "t_Department", pk="FItemID",
       search_fields=("FNumber", "FName"), code_field="FNumber", name_field="FName", default_order="FNumber"),
    _e("employee", "职员", "base", "t_Emp", pk="FItemID",
       search_fields=("FNumber", "FName"), code_field="FNumber", name_field="FName", default_order="FNumber"),
    _e("stock", "仓库", "base", "t_Stock", pk="FItemID",
       search_fields=("FNumber", "FName"), code_field="FNumber", name_field="FName", default_order="FNumber"),
    _e("stock_place", "仓位", "base", "t_StockPlace", pk="FSPID",
       search_fields=("FNumber", "FName"), proven="likely"),
    _e("item", "物料/商品", "base", "t_ICItem", pk="FItemID",
       select_fields="FItemID, FNumber, FName, FModel, FFullName, FItemClassID, FParentID, "
                     "FErpClsID, FUnitID, FUseState, FDeleted, FModifyTime",
       search_fields=("FNumber", "FName", "FModel"), code_field="FNumber", name_field="FName",
       default_order="FNumber", note="t_ICItem 为视图，汇聚 ICItemCore/Base/Material 等"),
    _e("item_core", "物料核心资料", "base", "t_ICItemCore", pk="FItemID", proven="likely"),
    _e("item_base", "物料基本资料", "base", "t_ICItemBase", pk="FItemID", proven="likely"),
    _e("item_material", "物料物流资料", "base", "t_ICItemMaterial", pk="FItemID", proven="likely"),
    _e("item_price", "物料价格资料", "base", "t_ICItemPrice", pk="FItemID", proven="likely"),
    _e("unit", "计量单位", "base", "t_MeasureUnit", pk="FMeasureUnitID",
       search_fields=("FNumber", "FName"), default_order="FNumber"),
    _e("currency", "币别", "base", "t_Currency", pk="FCurrencyID",
       search_fields=("FNumber", "FName"), default_order="FNumber"),
    _e("rate", "汇率", "base", "t_ExchangeRateEntry", pk="FExchangeRateEntryID",
       date_field="FDate", proven="likely", note="主表 t_ExchangeRate；本实体直接读分录表"),
    _e("item_class", "核算项目", "base", "t_Item", pk="FItemID",
       select_fields="FItemID, FItemClassID, FNumber, FName, FParentID, FLevel, FDetail, FFullNumber",
       search_fields=("FNumber", "FName", "FFullNumber"), default_order="FItemClassID, FNumber",
       note="FItemClassID: 1客户 2部门 3职员 4商品 5仓位 7单位 8供应商"),
    _e("item_class_def", "核算项目类别", "base", "t_ItemClass", pk="FItemClassID",
       search_fields=("FNumber", "FName"), proven="likely"),
    _e("item_detail", "核算项目使用详情(横表)", "base", "t_ItemDetail", pk="FDetailID", proven="likely"),
    _e("item_detail_v", "核算项目使用详情(纵表)", "base", "t_ItemDetailV", pk="FDetailID", proven="likely"),
    _e("aux_item", "辅助资料", "base", "t_SubMessage", pk="FInterID",
       search_fields=("FName", "FNumber"), proven="likely"),
    _e("aux_type", "辅助资料类别", "base", "SubMesType", pk="FTypeID", proven="likely"),
    _e("settlement", "结算方式", "base", "t_Settle", pk="FItemID", proven="likely"),
    _e("bank_account", "银行账户", "base", "t_BankAccount", pk="FAccountID", proven="likely"),
    _e("period", "会计期间", "base", "t_PeriodDate", pk="FPeriodDateID",
       date_field="FStartDate", default_order="FYear, FPeriod",
       note="按日期定位期间: FStartDate<=日期<=FEndDate"),
    _e("voucher_group", "凭证字", "base", "t_VoucherGroup", pk="FGroupID",
       search_fields=("FGroupName",), proven="likely"),
    _e("expense", "凭证摘要", "base", "t_VoucherExp", pk="FExpID",
       search_fields=("FName",), proven="likely"),
    _e("user", "用户", "base", "t_User", pk="FUserID", proven="likely",
       note="用户/权限相关表版本差异较大，仅作读取"),
]

# ---------------------------------------------------------------- 财务会计
FINANCE_ENTITIES: List[Entity] = [
    _e("voucher", "记账凭证", "finance", "t_Voucher", pk="FVoucherID",
       entry_table="t_VoucherEntry", entry_link="FVoucherID", entry_pk="FEntryID",
       select_fields="FVoucherID, FDate, FYear, FPeriod, FGroupID, FNumber, FReference, "
                     "FExplanation, FAttachments, FPreparedByID, FCheckedByID, FPostedByID, "
                     "FPostStatus, FTranType, FSerialNum",
       date_field="FDate", search_fields=("FExplanation", "FNumber", "FReference"),
       default_order="FDate DESC, FNumber DESC",
       note="FPostStatus: 0未过账 1已过账；分录在 t_VoucherEntry"),
    _e("voucher_entry", "凭证分录", "finance", "t_VoucherEntry", pk="FEntryID",
       select_fields="FEntryID, FVoucherID, FExplanation, FAccountID, FDetailID, FCurrencyID, "
                     "FExchangeRateType, FAmountFor, FDebit, FCredit, FQuantity, FMeasureUnitID",
       default_order="FVoucherID, FEntryID"),
    _e("balance", "科目余额", "finance", "t_Balance", pk="FBalanceID",
       select_fields="*", default_order="FYear, FPeriod, FAccountID",
       note="含期初/本期发生/期末余额，是自定义报表的主要数据源"),
    _e("profit_loss", "损益表数据", "finance", "t_ProfitAndLoss", pk="FInterID", proven="likely"),
    _e("cashflow_item", "现金流量项目", "finance", "t_CashFlowItem", pk="FItemID", proven="likely"),
    _e("initial_balance", "科目期初余额", "finance", "t_Balance", pk="FBalanceID",
       fixed_where="FPeriod = 0", proven="likely",
       note="FPeriod=0 通常表示期初；如与账套不符请用 balance 自行过滤"),
]

# ---------------------------------------------------------------- 供应链
SUPPLY_ENTITIES: List[Entity] = [
    _e("sale_order", "销售订单", "supply", "SEOrder", pk="FInterID",
       entry_table="SEOrderEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", search_fields=("FBillNo",), default_order="FDate DESC",
       note="表头 SEOrder / 表体 SEOrderEntry"),
    _e("sale_order_entry", "销售订单分录", "supply", "SEOrderEntry", pk="FEntryID",
       default_order="FInterID, FEntryID"),
    _e("sale_outstock", "销售出库单", "supply", "ICStockBill", pk="FInterID",
       entry_table="ICStockBillEntry", entry_link="FInterID", entry_pk="FEntryID",
       fixed_where="FTranType = 21", date_field="FDate", search_fields=("FBillNo", "FExplanation"),
       default_order="FDate DESC"),
    _e("sale_invoice", "销售发票", "supply", "ICSale", pk="FInterID",
       entry_table="ICSaleEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", search_fields=("FBillNo",), default_order="FDate DESC"),
    _e("sale_quote", "销售报价单", "supply", "PORFQ", pk="FInterID",
       entry_table="PORFQEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", search_fields=("FBillNo",), proven="likely"),
    _e("purchase_order", "采购订单", "supply", "POOrder", pk="FInterID",
       entry_table="POOrderEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", search_fields=("FBillNo", "FExplanation"), default_order="FDate DESC"),
    _e("purchase_order_entry", "采购订单分录", "supply", "POOrderEntry", pk="FEntryID",
       default_order="FInterID, FEntryID"),
    _e("purchase_instock", "采购入库单", "supply", "ICStockBill", pk="FInterID",
       entry_table="ICStockBillEntry", entry_link="FInterID", entry_pk="FEntryID",
       fixed_where="FTranType = 1", date_field="FDate", search_fields=("FBillNo", "FExplanation"),
       default_order="FDate DESC"),
    _e("purchase_invoice", "采购发票", "supply", "ICPurBill", pk="FInterID",
       entry_table="ICPurEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", search_fields=("FBillNo",), default_order="FDate DESC", proven="likely",
       note="部分版本表名为 ICPurchase/ICPurchaseEntry，可用 discover 校验"),
    _e("purchase_request", "采购申请单", "supply", "PORequest", pk="FInterID",
       entry_table="PORequestEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", proven="likely"),
    _e("other_instock", "其他入库单", "supply", "ICStockBill", pk="FInterID",
       entry_table="ICStockBillEntry", entry_link="FInterID", entry_pk="FEntryID",
       fixed_where="FTranType = 10", date_field="FDate", search_fields=("FBillNo",)),
    _e("other_outstock", "其他出库单", "supply", "ICStockBill", pk="FInterID",
       entry_table="ICStockBillEntry", entry_link="FInterID", entry_pk="FEntryID",
       fixed_where="FTranType = 29", date_field="FDate", search_fields=("FBillNo",)),
    _e("prod_instock", "产品入库单", "supply", "ICStockBill", pk="FInterID",
       entry_table="ICStockBillEntry", entry_link="FInterID", entry_pk="FEntryID",
       fixed_where="FTranType = 2", date_field="FDate", proven="likely"),
    _e("material_outstock", "生产领料单", "supply", "ICStockBill", pk="FInterID",
       entry_table="ICStockBillEntry", entry_link="FInterID", entry_pk="FEntryID",
       fixed_where="FTranType = 24", date_field="FDate", proven="likely"),
    _e("transfer", "调拨单", "supply", "ICStockBill", pk="FInterID",
       entry_table="ICStockBillEntry", entry_link="FInterID", entry_pk="FEntryID",
       fixed_where="FTranType = 41", date_field="FDate", search_fields=("FBillNo",)),
    _e("stock_bill", "出入库单(全部类型)", "supply", "ICStockBill", pk="FInterID",
       entry_table="ICStockBillEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", search_fields=("FBillNo",), default_order="FDate DESC",
       note="需按 FTranType 过滤单据类型，见 BILL_TRAN_TYPES"),
    _e("inventory", "即时库存", "supply", "ICInventory", pk="FInterID",
       select_fields="*", proven="likely",
       note="即时库存余额；统计库存通常与 t_Stock / t_ICItem 关联"),
    _e("inv_balance", "存货余额总表", "supply", "ICBal", pk="FInterID", proven="likely"),
    _e("inv_balance_detail", "存货余额明细表", "supply", "ICInvBal", pk="FInterID", proven="likely"),
    _e("batch", "批号库存", "supply", "ICInventoryBatch", pk="FInterID", proven="likely"),
]

# ---------------------------------------------------------------- 生产制造
MFG_ENTITIES: List[Entity] = [
    _e("mo", "生产任务单", "mfg", "ICmo", pk="FInterID",
       entry_table="ICmoEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", search_fields=("FBillNo",), proven="likely"),
    _e("ppbom", "生产投料单", "mfg", "PPBom", pk="FInterID",
       entry_table="PPBomEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", proven="likely"),
    _e("subcontract", "委外订单", "mfg", "ICSubContract", pk="FInterID",
       entry_table="ICSubContractEntry", entry_link="FInterID", entry_pk="FEntryID",
       date_field="FDate", proven="likely"),
    _e("bom", "BOM 物料清单", "mfg", "ICBom", pk="FInterID",
       entry_table="ICBomEntry", entry_link="FInterID", entry_pk="FEntryID", proven="likely"),
    _e("routing", "工艺路线", "mfg", "t_Routing", pk="FInterID", proven="likely"),
]

# ---------------------------------------------------------------- 应收应付
ARAP_ENTITIES: List[Entity] = [
    _e("receivable", "应收单", "arap", "t_RP_Contact", pk="FInterID",
       fixed_where="FRP = 1", date_field="FDate", search_fields=("FBillNo",),
       default_order="FDate DESC", note="FRP=1 应收"),
    _e("payable", "应付单", "arap", "t_RP_Contact", pk="FInterID",
       fixed_where="FRP = 0", date_field="FDate", search_fields=("FBillNo",),
       default_order="FDate DESC", note="FRP=0 应付"),
    _e("rp_contact", "应收应付单(全部)", "arap", "t_RP_Contact", pk="FInterID",
       date_field="FDate", search_fields=("FBillNo",), default_order="FDate DESC"),
    _e("receive_bill", "收款单", "arap", "t_RP_NewReceiveBill", pk="FInterID",
       date_field="FDate", proven="likely", note="版本差异较大，请用 discover 校验表名"),
    _e("pay_bill", "付款单", "arap", "t_RP_NewPayBill", pk="FInterID",
       date_field="FDate", proven="likely"),
    _e("rp_check_detail", "核销明细", "arap", "t_RP_CheckDetail", pk="FInterID", proven="likely"),
    _e("rp_contact_bal", "往来余额表", "arap", "t_RP_ContactBal", pk="FInterID",
       note="FRP=1 应收 / FRP=0 应付", proven="likely"),
    _e("rp_contract", "合同(应收)", "arap", "t_RPContract", pk="FContractID",
       search_fields=("FContractNO", "FName"), proven="likely"),
    _e("rp_contract_scheme", "收款计划明细", "arap", "t_RPContractScheme", pk="FInterID", proven="likely"),
]

# ---------------------------------------------------------------- 系统/元数据
SYSTEM_ENTITIES: List[Entity] = [
    _e("table_desc", "数据表描述", "system", "t_TableDescription", pk="FTableID",
       search_fields=("FTableName", "FDescription"),
       note="查金蝶表中文名: SELECT * FROM t_TableDescription WHERE FTableName='t_Voucher'"),
    _e("field_desc", "字段描述", "system", "t_FieldDescription", pk="FFieldID",
       search_fields=("FFieldName", "FDescription")),
    _e("log", "操作日志", "system", "t_Log", pk="FLogID", date_field="FDate", proven="likely"),
    _e("max_num", "单据最大内码", "system", "ICMaxNum", pk="FMaxNumID", proven="likely",
       note="导入数据后需同步维护，否则新增单据会报主键冲突"),
]

ENTITIES: Dict[str, Entity] = {}
for _list in (BASE_ENTITIES, FINANCE_ENTITIES, SUPPLY_ENTITIES, MFG_ENTITIES, ARAP_ENTITIES, SYSTEM_ENTITIES):
    for _ent in _list:
        ENTITIES[_ent.key] = _ent

# 单据类型（ICStockBill.FTranType）
BILL_TRAN_TYPES: Dict[int, str] = {
    1: "采购入库",
    2: "产品入库",
    10: "其他入库",
    21: "销售出库",
    24: "生产领料",
    28: "委外加工发出",
    29: "其他出库",
    41: "调拨单",
    100: "成本调整单",
}

# 核算项目类别（t_Item.FItemClassID）
ITEM_CLASS_IDS: Dict[int, str] = {
    1: "客户", 2: "部门", 3: "职员", 4: "商品(物料)", 5: "仓位",
    7: "单位", 8: "供应商",
}

MODULE_LABELS: Dict[str, str] = {
    "base": "基础资料",
    "finance": "财务会计",
    "supply": "供应链/库存",
    "mfg": "生产制造",
    "arap": "应收应付",
    "system": "系统/元数据",
}


def get_entity(key: str) -> Entity:
    ent = ENTITIES.get(key)
    if not ent:
        raise KeyError(
            f"未知实体: {key!r}。可用 kis_list_entities 查看全部实体（共 {len(ENTITIES)} 个）"
        )
    return ent


def catalog(module: Optional[str] = None) -> List[Dict[str, object]]:
    return [e.to_dict() for e in ENTITIES.values() if module in (None, e.module)]


def modules() -> List[Dict[str, object]]:
    out = []
    for key, label in MODULE_LABELS.items():
        out.append({
            "module": key,
            "label": label,
            "count": sum(1 for e in ENTITIES.values() if e.module == key),
        })
    return out
