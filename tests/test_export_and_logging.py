# date: 2026-11-09 18:40
# author: cody
# description: Excel 导出、紧凑序列化、错误摘要、关键词字段与 MCP 调用日志的单元测试（不依赖 COM / 金蝶客户端）

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

import openpyxl
from openpyxl import load_workbook

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from kingdeeflagship_mcp import mcp_server  # noqa: E402
from kingdeeflagship_mcp.errors import KISError, summarize_error  # noqa: E402
from kingdeeflagship_mcp.exporter import display, require_openpyxl, safe_filename, safe_sheet_name, write_xlsx  # noqa: E402
from kingdeeflagship_mcp.models import PageResult, Query  # noqa: E402
from kingdeeflagship_mcp.schema import get_entity  # noqa: E402
from kingdeeflagship_mcp.sqlbuilder import build_select  # noqa: E402


class ExporterTest(unittest.TestCase):
    def test_display(self):
        self.assertEqual(display(None), "")
        self.assertEqual(display(Decimal("12.50")), "12.50")
        self.assertEqual(display(datetime(2026, 11, 9)), "2026-11-09")
        self.assertEqual(display(datetime(2026, 11, 9, 8, 5, 3, 999)), "2026-11-09 08:05:03")
        self.assertEqual(display(datetime(2026, 11, 9, 8, 5, tzinfo=timezone.utc)), "2026-11-09 08:05:00")
        self.assertEqual(display(date(2026, 11, 9)), "2026-11-09")
        self.assertEqual(display(b"\x01\xff"), "01ff")

    def test_safe_filename(self):
        self.assertEqual(safe_filename("a.xlsx", "d"), "a.xlsx")
        self.assertEqual(safe_filename("a", "d"), "a.xlsx")
        self.assertEqual(safe_filename("a.csv", "d"), "a.xlsx")
        self.assertEqual(safe_filename("报表", "d"), "报表.xlsx")
        self.assertEqual(safe_filename("../../evil", "d"), "evil.xlsx")
        self.assertEqual(safe_filename("a:b*c?", "d"), "a_b_c_.xlsx")
        self.assertEqual(safe_filename("", "d"), "d.xlsx")
        self.assertEqual(safe_filename("CON", "d"), "d.xlsx")

    def test_safe_sheet_name(self):
        self.assertEqual(safe_sheet_name("汇总", 1, []), "汇总")
        self.assertEqual(safe_sheet_name("a/b:c*d?e[f]g", 1, []), "a_b_c_d_e_f_g")
        self.assertEqual(safe_sheet_name("", 3, []), "Sheet3")
        self.assertEqual(safe_sheet_name("  ", 2, []), "Sheet2")
        self.assertEqual(safe_sheet_name("x" * 40, 1, []), "x" * 31)
        self.assertEqual(safe_sheet_name("History", 1, []), "History_")
        self.assertEqual(safe_sheet_name("'abc'", 1, []), "abc")
        self.assertEqual(safe_sheet_name("明细", 2, ["明细"]), "明细_2")
        self.assertEqual(safe_sheet_name("ABC", 2, ["abc"]), "ABC_2")
        self.assertEqual(len(safe_sheet_name("y" * 40, 2, ["y" * 31])), 31)

    def test_write_xlsx_content_and_types(self):
        rows = [
            {"订单号": "PO1", "日期": datetime(2026, 10, 21), "物料编码": "01.02.003", "数量": Decimal("10.0000"),
             "金额": Decimal("355.5"), "备注": "=SUM(A1)", "时间": datetime(2026, 10, 21, 8, 30, tzinfo=timezone.utc),
             "脏": "a\x00b"},
            {"订单号": "PO2", "日期": None, "物料编码": "0012", "数量": 3, "金额": None, "备注": "+1 x",
             "时间": None, "脏": "ok"},
        ]
        with tempfile.TemporaryDirectory() as d:
            info = write_xlsx([("明细", rows)], d, "明细", "default")
            self.assertEqual(os.path.basename(info["path"]), "明细.xlsx")
            ws = load_workbook(info["path"]).active
            self.assertEqual(ws.title, "明细")
            self.assertEqual(ws.freeze_panes, "A2")
            header = [c.value for c in ws[1]]
            self.assertEqual(header, ["订单号", "日期", "物料编码", "数量", "金额", "备注", "时间", "脏"])
            self.assertTrue(all(c.font.bold for c in ws[1]))
            r1 = {h: c for h, c in zip(header, ws[2])}
            r2 = {h: c for h, c in zip(header, ws[3])}
            self.assertEqual(r1["物料编码"].value, "01.02.003")
            self.assertEqual(r2["物料编码"].value, "0012")
            self.assertEqual(r2["物料编码"].data_type, "s")
            self.assertEqual(r1["数量"].value, 10)
            self.assertEqual(r1["金额"].value, 355.5)
            self.assertEqual(r2["数量"].value, 3)
            self.assertIsNone(r2["金额"].value)
            self.assertEqual(r1["日期"].value, datetime(2026, 10, 21))
            self.assertEqual(r1["日期"].number_format, "yyyy-mm-dd")
            self.assertEqual(r1["时间"].value, datetime(2026, 10, 21, 8, 30))
            self.assertEqual(r1["备注"].value, "=SUM(A1)")
            self.assertEqual(r1["备注"].data_type, "s")
            self.assertEqual(r1["脏"].value, "ab")
            sh = info["sheets"][0]
            self.assertEqual((sh["rows"], len(sh["columns"])), (2, 8))
            self.assertEqual(len(sh["preview"]), 2)
            self.assertEqual(sh["preview"][0]["时间"], "2026-10-21 08:30:00")

    def test_multiple_sheets_in_one_file(self):
        with tempfile.TemporaryDirectory() as d:
            info = write_xlsx([("汇总", [{"项目": "苏大", "金额": Decimal("9700")}]),
                               ("明细", [{"编码": "A1", "数量": 8}, {"编码": "A2", "数量": 1}]),
                               ("明细", [{"x": 1}])], d, "苏大", "default")
            self.assertEqual([s["name"] for s in info["sheets"]], ["汇总", "明细", "明细_2"])
            wb = load_workbook(info["path"])
            self.assertEqual(wb.sheetnames, ["汇总", "明细", "明细_2"])
            self.assertEqual(wb["汇总"]["B2"].value, 9700)
            self.assertEqual(wb["明细"].max_row, 3)
            self.assertEqual(wb["明细"]["A1"].value, "编码")
            self.assertEqual(wb["明细"].freeze_panes, "A2")
            self.assertEqual(len(os.listdir(d)), 1)

    def test_empty_sheet_gets_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            info = write_xlsx([("有", [{"a": 1}]), ("空", [])], d, "e", "default")
            wb = load_workbook(info["path"])
            self.assertEqual(wb["空"]["A1"].value, "（无数据）")
            self.assertEqual([s["rows"] for s in info["sheets"]], [1, 0])

    def test_formula_like_header_stays_text(self):
        with tempfile.TemporaryDirectory() as d:
            info = write_xlsx([("数据", [{"=bad": 1}])], d, "h", "default")
            cell = load_workbook(info["path"]).active["A1"]
            self.assertEqual((cell.value, cell.data_type), ("=bad", "s"))

    def test_column_width_clamped(self):
        with tempfile.TemporaryDirectory() as d:
            info = write_xlsx([("数据", [{"短": "a", "长": "字" * 100}])], d, "w", "default")
            dims = load_workbook(info["path"]).active.column_dimensions
            self.assertEqual(dims["A"].width, 8)
            self.assertEqual(dims["B"].width, 50)

    def test_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            a = write_xlsx([("数据", [{"a": 1}])], d, "same", "default")["path"]
            b = write_xlsx([("数据", [{"a": 2}])], d, "same", "default")["path"]
            self.assertNotEqual(a, b)
            self.assertTrue(os.path.exists(a) and os.path.exists(b))
            self.assertEqual(os.path.dirname(b), d)

    def test_all_empty_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                write_xlsx([], d, "x", "default")
            with self.assertRaises(ValueError):
                write_xlsx([("a", []), ("b", [])], d, "x", "default")

    def test_missing_openpyxl_gives_hint(self):
        with mock.patch.dict(sys.modules, {"openpyxl": None}):
            with self.assertRaises(KISError) as cm:
                require_openpyxl()
        self.assertIn("openpyxl", cm.exception.message)
        self.assertIn("pip install", cm.exception.hint)

    def test_failed_save_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(openpyxl.Workbook, "save", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    write_xlsx([("数据", [{"a": 1}])], d, "x", "default")
            self.assertEqual(os.listdir(d), [])


class RenderAndErrorTest(unittest.TestCase):
    def test_compact_json_has_no_indent(self):
        text, full = mcp_server._render({"a": [1, 2], "b": "中"})
        self.assertEqual(text, '{"a":[1,2],"b":"中"}')
        self.assertEqual(full, len(text))

    def test_truncation_reports_full_length(self):
        big = {"x": "a" * (mcp_server.MAX_TEXT + 100)}
        stats = {}
        resp = mcp_server._ok(big, stats)
        self.assertTrue(stats["truncated"])
        self.assertGreater(stats["full_chars"], mcp_server.MAX_TEXT)
        self.assertEqual(stats["result_chars"], len(resp["content"][0]["text"]))
        self.assertIn("kis_export", resp["content"][0]["text"])

    def test_small_result_not_truncated(self):
        stats = {}
        mcp_server._ok({"a": 1}, stats)
        self.assertFalse(stats["truncated"])
        self.assertNotIn("full_chars", stats)

    def test_shape(self):
        pr = PageResult(entity="e", rows=[{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        self.assertEqual(mcp_server._shape(pr), {"rows": 2, "cols": 2})
        self.assertEqual(mcp_server._shape({"rows": []}), {"rows": 0, "cols": 0})
        self.assertEqual(mcp_server._shape({"status": "ok"}), {})

    def test_summarize_error_com_style(self):
        e = Exception(-2147352567, "发生意外。",
                      (0, "Microsoft OLE DB Provider for SQL Server", "列名 'FMemo' 无效。", None, 0, -1), None)
        self.assertEqual(summarize_error(e), "列名 'FMemo' 无效。")

    def test_summarize_error_plain(self):
        self.assertEqual(summarize_error(KISError("出错了")), "出错了")
        self.assertEqual(len(summarize_error(Exception("x" * 500))), 200)


class KeywordFieldTest(unittest.TestCase):
    def test_remark_searched_for_selected_entities(self):
        for key in ("purchase_order", "purchase_instock", "sale_outstock"):
            ent = get_entity(key)
            self.assertEqual(ent.search_fields, ("FBillNo", "FExplanation"), key)
            sql, params = build_select(ent, Query(entity=key, keyword="苏大"))
            self.assertIn("[FExplanation] LIKE ?", sql)
            self.assertEqual(params.count("%苏大%"), 2)

    def test_other_entities_unchanged(self):
        self.assertEqual(get_entity("sale_order").search_fields, ("FBillNo",))


class McpLoggingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"KIS_HOME": self._tmp.name})
        patcher.start()
        os.environ.pop("KIS_CONFIG", None)
        self.addCleanup(patcher.stop)
        self.srv = mcp_server.MCPServer()
        self.log_path = self.srv.kis.logger.path

    def tearDown(self):
        self.srv.kis.close()
        self._tmp.cleanup()

    def _events(self):
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def _call(self, tool, args):
        return self.srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": tool, "arguments": args}})

    def test_success_event_has_size_fields(self):
        resp = self._call("kis_list_entities", {"keyword": "采购"})
        self.assertFalse(resp["result"]["isError"])
        ev = [e for e in self._events() if e["event"] == "mcp_tool"][-1]
        self.assertEqual(ev["tool"], "kis_list_entities")
        self.assertTrue(ev["ok"])
        self.assertEqual(ev["result_chars"], len(resp["result"]["content"][0]["text"]))
        self.assertGreater(ev["args_chars"], 0)
        self.assertFalse(ev["truncated"])
        self.assertIn("dur_s", ev)

    def test_failure_event_has_summary(self):
        resp = self._call("kis_output", {"action": "set"})
        self.assertTrue(resp["result"]["isError"])
        ev = [e for e in self._events() if e["event"] == "mcp_tool_failed"][-1]
        self.assertEqual(ev["tool"], "kis_output")
        self.assertTrue(ev["error_summary"])
        self.assertGreater(ev["result_chars"], 0)

    def test_initialize_and_tools_list_events(self):
        self.srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"clientInfo": {"name": "WorkBuddy", "version": "1"}}})
        self.srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        evs = {e["event"]: e for e in self._events()}
        self.assertEqual(evs["mcp_initialize"]["instructions_chars"], len(mcp_server.SERVER_INSTRUCTIONS))
        self.assertEqual(evs["mcp_initialize"]["client"]["name"], "WorkBuddy")
        self.assertEqual(evs["mcp_tools_list"]["tools"], len(mcp_server.TOOLS))
        self.assertGreater(evs["mcp_tools_list"]["tools_chars"], 0)

    def test_session_summary_written_on_exit(self):
        self._call("kis_list_entities", {})
        self._call("kis_list_entities", {})
        self._call("kis_output", {"action": "set"})
        with mock.patch.object(sys, "stdin", iter([])):
            self.srv.serve()
        summ = [e for e in self._events() if e["event"] == "session_summary"][-1]
        self.assertEqual(summ["total_calls"], 3)
        self.assertEqual(summ["total_failed"], 1)
        self.assertEqual(summ["tools"]["kis_list_entities"]["calls"], 2)
        self.assertEqual(summ["tools"]["kis_output"]["failed"], 1)


class ExportSqlTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"KIS_HOME": self._tmp.name})
        patcher.start()
        os.environ.pop("KIS_CONFIG", None)
        self.addCleanup(patcher.stop)
        self.srv = mcp_server.MCPServer()
        self.kis = self.srv.kis
        self.calls = []
        self.rows = [{"订单号": "PO1", "备注": "SECRETVAL"}]
        self.results = {}
        self.errors = {}
        self.warnings = {}
        self.out = os.path.join(self._tmp.name, "out")

        outer = self

        class FakeBackend:
            connected = True

            def raw_sql(self, sql, params=None, max_rows=None):
                outer.calls.append(max_rows)
                if sql in outer.errors:
                    raise outer.errors[sql]
                rows = outer.results.get(sql, outer.rows)
                return PageResult(entity="raw_sql", rows=rows, total=len(rows),
                                  warnings=outer.warnings.get(sql, []))

        self.kis.backend = FakeBackend()
        self.kis.backend_name = "com"

    def tearDown(self):
        self.kis.backend = None
        self.kis.close()
        self._tmp.cleanup()

    def _events(self, name):
        with open(self.kis.logger.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if f'"event": "{name}"' in line]

    def test_requires_output_dir(self):
        with self.assertRaises(KISError):
            self.kis.export_sql("select 1")

    def test_argument_validation(self):
        with self.assertRaises(KISError):
            self.kis.export_sql()
        with self.assertRaises(KISError):
            self.kis.export_sql("q1", sheets=[{"sql": "q1"}])
        with self.assertRaises(KISError):
            self.kis.export_sql(sheets=[{"name": "无sql"}])
        with self.assertRaises(KISError):
            self.kis.export_sql(sheets=[{"sql": "q1"}] * 21)

    def test_exports_xlsx_and_logs_without_row_data(self):
        self.kis.set_output_dir(self.out)
        info = self.kis.export_sql("select 1", filename="明细")
        self.assertTrue(info["exported"])
        self.assertEqual(os.path.dirname(info["path"]), self.out)
        self.assertTrue(info["path"].endswith(".xlsx"))
        self.assertEqual(self.calls, [50000])
        self.assertFalse(info["truncated"])
        self.assertEqual(info["rows"], 1)
        self.assertEqual(info["sheets"][0]["columns"], ["订单号", "备注"])
        self.assertEqual(load_workbook(info["path"]).active["B2"].value, "SECRETVAL")
        ev = self._events("export")[-1]
        self.assertEqual((ev["sheets"], ev["rows"], ev["sheet_rows"]), (1, 1, [1]))
        with open(self.kis.logger.path, encoding="utf-8") as f:
            self.assertNotIn("SECRETVAL", f.read())

    def test_multi_sheet_export(self):
        self.kis.set_output_dir(self.out)
        self.results = {"q1": [{"项目": "苏大"}],
                        "q2": [{"编码": "A1", "数量": 8}, {"编码": "A2", "数量": 1}]}
        info = self.kis.export_sql(filename="苏大", sheets=[{"name": "汇总", "sql": "q1"},
                                                          {"name": "明细", "sql": "q2"}])
        self.assertEqual(load_workbook(info["path"]).sheetnames, ["汇总", "明细"])
        self.assertEqual(info["rows"], 3)
        self.assertEqual([s["rows"] for s in info["sheets"]], [1, 2])
        self.assertEqual(self.calls, [50000, 50000])
        ev = self._events("export")[-1]
        self.assertEqual((ev["sheets"], ev["rows"], ev["sheet_rows"]), (2, 3, [1, 2]))

    def test_multi_sheet_failure_names_sheet_and_writes_nothing(self):
        self.kis.set_output_dir(self.out)
        self.errors = {"bad": Exception(-1, "x", (0, "p", "列名 'FMemo' 无效。", None, 0, -1), None)}
        with self.assertRaises(KISError) as cm:
            self.kis.export_sql(sheets=[{"name": "好", "sql": "q1"}, {"name": "坏", "sql": "bad"}])
        self.assertIn("坏", cm.exception.message)
        self.assertIn("FMemo", cm.exception.message)
        self.assertEqual(os.listdir(self.out), [])

    def test_single_sheet_failure_keeps_original_exception(self):
        self.kis.set_output_dir(self.out)
        self.errors = {"bad": ValueError("boom")}
        with self.assertRaises(ValueError):
            self.kis.export_sql("bad")

    def test_empty_result_creates_no_file(self):
        self.kis.set_output_dir(self.out)
        self.rows = []
        info = self.kis.export_sql("select 1")
        self.assertFalse(info["exported"])
        self.assertEqual(os.listdir(self.out), [])

    def test_one_empty_sheet_still_exports(self):
        self.kis.set_output_dir(self.out)
        self.results = {"q1": [{"a": 1}], "q2": []}
        info = self.kis.export_sql(sheets=[{"name": "有", "sql": "q1"}, {"name": "空", "sql": "q2"}])
        self.assertTrue(info["exported"])
        self.assertEqual([s["rows"] for s in info["sheets"]], [1, 0])

    def test_truncation_flag(self):
        self.kis.set_output_dir(self.out)
        self.warnings = {"select 1": ["结果超过 50000 行已截断"]}
        info = self.kis.export_sql("select 1")
        self.assertTrue(info["truncated"])
        self.assertTrue(info["sheets"][0]["truncated"])

    def test_missing_openpyxl_fails_before_query(self):
        self.kis.set_output_dir(self.out)
        with mock.patch.dict(sys.modules, {"openpyxl": None}):
            with self.assertRaises(KISError):
                self.kis.export_sql("select 1")
        self.assertEqual(self.calls, [])

    def test_tool_schema_allows_sheets(self):
        tool = [t for t in mcp_server.TOOLS if t["name"] == "kis_export"][0]
        self.assertIn("sheets", tool["inputSchema"]["properties"])
        self.assertNotIn("required", tool["inputSchema"])


if __name__ == "__main__":
    unittest.main()
