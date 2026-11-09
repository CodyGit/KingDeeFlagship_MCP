# date: 2026-11-09 18:40
# author: cody
# description: CSV 导出、紧凑序列化、错误摘要、关键词字段与 MCP 调用日志的单元测试（不依赖 COM / 金蝶客户端）

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from kingdeeflagship_mcp import mcp_server  # noqa: E402
from kingdeeflagship_mcp.errors import KISError, summarize_error  # noqa: E402
from kingdeeflagship_mcp.exporter import cell, safe_filename, write_csv  # noqa: E402
from kingdeeflagship_mcp.models import PageResult, Query  # noqa: E402
from kingdeeflagship_mcp.schema import get_entity  # noqa: E402
from kingdeeflagship_mcp.sqlbuilder import build_select  # noqa: E402


class ExporterTest(unittest.TestCase):
    def test_cell_conversion(self):
        self.assertEqual(cell(None), "")
        self.assertEqual(cell(Decimal("12.50")), "12.50")
        self.assertEqual(cell(datetime(2026, 11, 9, 8, 5, 3, 999)), "2026-11-09 08:05:03")
        self.assertEqual(cell(date(2026, 11, 9)), "2026-11-09")
        self.assertEqual(cell(b"\x01\xff"), "01ff")

    def test_safe_filename(self):
        self.assertEqual(safe_filename("a.csv", "d"), "a.csv")
        self.assertEqual(safe_filename("报表", "d"), "报表.csv")
        self.assertEqual(safe_filename("../../evil", "d"), "evil.csv")
        self.assertEqual(safe_filename("a:b*c?", "d"), "a_b_c_.csv")
        self.assertEqual(safe_filename("", "d"), "d.csv")
        self.assertEqual(safe_filename("CON", "d"), "d.csv")

    def test_write_csv_content_and_bom(self):
        rows = [{"单号": "PO1", "金额": Decimal("1.5"), "日期": datetime(2026, 1, 2, 3, 4, 5)},
                {"单号": "PO2", "金额": None, "日期": None}]
        with tempfile.TemporaryDirectory() as d:
            info = write_csv(rows, d, "x", "default")
            with open(info["path"], "rb") as f:
                self.assertTrue(f.read().startswith(b"\xef\xbb\xbf"))
            with open(info["path"], encoding="utf-8-sig", newline="") as f:
                got = list(csv.reader(f))
            self.assertEqual(got[0], ["单号", "金额", "日期"])
            self.assertEqual(got[1], ["PO1", "1.5", "2026-01-02 03:04:05"])
            self.assertEqual(got[2], ["PO2", "", ""])
            self.assertEqual((info["rows"], len(info["columns"])), (2, 3))
            self.assertEqual(len(info["preview"]), 2)

    def test_write_csv_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            a = write_csv([{"a": 1}], d, "same", "default")["path"]
            b = write_csv([{"a": 2}], d, "same", "default")["path"]
            self.assertNotEqual(a, b)
            self.assertTrue(os.path.exists(a) and os.path.exists(b))
            self.assertEqual(os.path.dirname(b), d)

    def test_write_csv_empty_rows_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                write_csv([], d, "x", "default")


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

        outer = self

        class FakeBackend:
            connected = True

            def raw_sql(self, sql, params=None, max_rows=None):
                outer.calls.append(max_rows)
                return PageResult(entity="raw_sql", rows=outer.rows, total=len(outer.rows),
                                  warnings=outer.warnings)

        self.rows = [{"a": 1, "b": "SECRETVAL"}]
        self.warnings = []
        self.kis.backend = FakeBackend()
        self.kis.backend_name = "com"

    def tearDown(self):
        self.kis.backend = None
        self.kis.close()
        self._tmp.cleanup()

    def test_requires_output_dir(self):
        with self.assertRaises(KISError):
            self.kis.export_sql("select 1")

    def test_exports_and_logs(self):
        out = os.path.join(self._tmp.name, "out")
        self.kis.set_output_dir(out)
        info = self.kis.export_sql("select 1", filename="明细")
        self.assertTrue(info["exported"])
        self.assertEqual(os.path.dirname(info["path"]), out)
        self.assertEqual(self.calls, [50000])
        self.assertFalse(info["truncated"])
        with open(self.kis.logger.path, encoding="utf-8") as f:
            ev = [json.loads(line) for line in f if '"event": "export"' in line][-1]
        self.assertEqual((ev["rows"], ev["cols"]), (1, 2))
        with open(self.kis.logger.path, encoding="utf-8") as f:
            self.assertNotIn("SECRETVAL", f.read())

    def test_empty_result_creates_no_file(self):
        out = os.path.join(self._tmp.name, "out")
        self.kis.set_output_dir(out)
        self.rows = []
        info = self.kis.export_sql("select 1")
        self.assertFalse(info["exported"])
        self.assertEqual(os.listdir(out), [])

    def test_truncation_flag(self):
        self.kis.set_output_dir(os.path.join(self._tmp.name, "out"))
        self.warnings = ["结果超过 50000 行已截断"]
        self.assertTrue(self.kis.export_sql("select 1")["truncated"])


if __name__ == "__main__":
    unittest.main()
