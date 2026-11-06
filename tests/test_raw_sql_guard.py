# date: 2026-11-06 10:50
# author: cody
# description: raw_sql 多语句检测与前缀白名单的单元测试（不依赖 COM / 金蝶客户端）

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from kingdeeflagship_mcp.backends.com_backend import COMBackend  # noqa: E402
from kingdeeflagship_mcp.config import Config  # noqa: E402
from kingdeeflagship_mcp.errors import WriteDenied  # noqa: E402
from kingdeeflagship_mcp.sqlbuilder import has_multiple_statements  # noqa: E402


class HasMultipleStatementsTest(unittest.TestCase):
    def test_single_statement(self):
        for sql in (
            "SELECT 1",
            "SELECT 1;",
            "SELECT 1 ;  ",
            "SELECT * FROM t_Account WHERE FName = 'a;b'",
            "SELECT * FROM t_Account WHERE FName = 'it''s;ok'",
            "SELECT [a;b] FROM t",
            "SELECT 1 -- trailing; comment",
            "SELECT 1 /* a; b */",
            "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
        ):
            self.assertFalse(has_multiple_statements(sql), sql)

    def test_multiple_statements(self):
        for sql in (
            "SELECT 1; DROP TABLE t_Account",
            "SELECT 1;SELECT 2",
            "SELECT 1; -- c\nDELETE FROM t",
            "SELECT 'x'; UPDATE t SET a=1",
            "SELECT 1 /* c */; DROP TABLE t",
        ):
            self.assertTrue(has_multiple_statements(sql), sql)


class RawSqlGuardTest(unittest.TestCase):
    """raw_sql 在触达数据库前就应拒绝：用未连接的后端即可验证（拒绝发生在 _db() 之前）。"""

    def setUp(self):
        self.backend = COMBackend(Config({"com": {}}))

    def assert_denied(self, sql):
        with self.assertRaises(WriteDenied):
            self.backend.raw_sql(sql)

    def test_denies_non_select_prefix(self):
        self.assert_denied("DELETE FROM t_Account")
        self.assert_denied("UPDATE t_Account SET FName = 'x'")

    def test_denies_multi_statement(self):
        self.assert_denied("SELECT 1; DROP TABLE t_Account")
        self.assert_denied("WITH x AS (SELECT 1 AS n) SELECT n FROM x; DELETE FROM t")


if __name__ == "__main__":
    unittest.main()
