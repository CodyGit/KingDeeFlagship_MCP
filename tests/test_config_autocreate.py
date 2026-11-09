# date: 2026-11-09 17:48
# author: cody
# description: Config.load 在默认配置路径不存在时自动生成 config.json 的单元测试

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from kingdeeflagship_mcp.config import DEFAULT_CONFIG, Config  # noqa: E402


class ConfigAutoCreateTest(unittest.TestCase):
    def test_creates_default_file_in_kis_home(self):
        with tempfile.TemporaryDirectory() as home:
            env = {"KIS_HOME": home}
            with mock.patch.dict(os.environ, env):
                os.environ.pop("KIS_CONFIG", None)
                cfg = Config.load()
            target = os.path.join(home, "config.json")
            self.assertTrue(os.path.exists(target))
            self.assertEqual(cfg.source, target)
            with open(target, encoding="utf-8") as f:
                self.assertEqual(json.load(f), DEFAULT_CONFIG)

    def test_existing_file_not_overwritten(self):
        with tempfile.TemporaryDirectory() as home:
            target = os.path.join(home, "config.json")
            with open(target, "w", encoding="utf-8") as f:
                json.dump({"subjects": {"苏大": {"acct_id": "X"}}}, f, ensure_ascii=False)
            with mock.patch.dict(os.environ, {"KIS_HOME": home}):
                os.environ.pop("KIS_CONFIG", None)
                cfg = Config.load()
            self.assertEqual(cfg.get("subjects")["苏大"]["acct_id"], "X")

    def test_explicit_path_not_created(self):
        with tempfile.TemporaryDirectory() as home:
            target = os.path.join(home, "nope.json")
            cfg = Config.load(target)
            self.assertFalse(os.path.exists(target))
            self.assertEqual(cfg.source, "<defaults>")

    def test_unwritable_home_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as home:
            blocker = os.path.join(home, "file")
            open(blocker, "w").close()
            with mock.patch.dict(os.environ, {"KIS_HOME": os.path.join(blocker, "sub")}):
                os.environ.pop("KIS_CONFIG", None)
                cfg = Config.load()
            self.assertEqual(cfg.source, "<defaults>")


if __name__ == "__main__":
    unittest.main()
