# -*- coding: utf-8 -*-
"""行为覆盖的分类必须准 —— 分错类，报告就会同时漏报和误报。

这份测试盯四件事：
1. 每条阻断判据都有分类（漏一条，报告就是残的）；
2. 被坏样本弄红过的，算「坏样本」；
3. **自身 run 就是反证的，不算 0 覆盖** —— 这是最容易分错的一类；
4. 没人弄红过的，不许冒充「坏样本」。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import coverage_check as Cov     # noqa: E402


class TestCoverage(unittest.TestCase):
    def setUp(self):
        self.rows = Cov.build_rows()
        self.by_id = {r["id"]: r["class"] for r in self.rows}

    def test_每条阻断判据都有分类(self):
        self.assertTrue(self.rows, "一份契约都没读到？")
        unknown = [r["id"] for r in self.rows if r["class"] not in Cov.LABELS]
        self.assertEqual([], unknown, "这些判据没有分类")

    def test_被坏样本弄红过的算坏样本(self):
        for cid in ("T5-a", "T7-a", "F2-a"):
            self.assertEqual("坏样本", self.by_id.get(cid), cid)

    def test_自身就是反证的判据不算零覆盖(self):
        """G5-b 的 run 是 `unittest tests.test_lock` —— 它就是「把契约改坏，看红不红」。"""
        for cid in ("G5-b", "R3-d"):
            self.assertEqual("自身即反证", self.by_id.get(cid), cid)

    def test_没人弄红过的不许冒充坏样本(self):
        for cid in ("R1-a", "L1-a"):
            self.assertEqual("仅正向", self.by_id.get(cid), cid)

    def test_坏样本判据确实有坏样本撑着(self):
        """分类叫「坏样本」，就得真有一份期望它红的用例；否则这个标签是编的。"""
        reds = Cov.red_ids()
        for row in self.rows:
            if row["class"] != "坏样本":
                continue
            self.assertIn(row["id"], reds.get(row["contract"], set()), row["id"])


if __name__ == "__main__":
    unittest.main()
