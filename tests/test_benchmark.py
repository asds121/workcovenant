# -*- coding: utf-8 -*-
"""基准集的回归钉子 —— 每条用例的期望值都钉死。

用例本体在 `tests/benchmark_cases.py`（六组）与 `tests/benchmark_data.py`（data 组）；
这里只负责"少了/错了就红"。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import benchmark_cases as B      # noqa: E402
from wvc import checks                      # noqa: E402
from wvc import contract as C               # noqa: E402


class TestBenchmark(unittest.TestCase):
    def test_全部用例符合预期(self):
        bad = [o.detail for o in B.run_all() if not o.ok]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_七组都覆盖到(self):
        """五类判据 + 契约校验 + 打分口径；少一组就等于有一类错误没人管。"""
        self.assertEqual({c.group for c in B.CASES},
                         {"cmd", "file", "links", "manual", "data", "contract", "score"})

    def test_用例id不重复(self):
        ids = [c.id for c in B.CASES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_每条用例都写了为什么(self):
        for c in B.CASES:
            self.assertTrue(c.why.strip(), f"{c.id} 没写守什么")

    def test_至少有三十条(self):
        """基准集的规模本身就是承诺：太少就说明只有一条路被验过。"""
        self.assertGreaterEqual(len(B.CASES), 30)

    def test_失败用例必须给出差在哪(self):
        """一条红不能只说"没过" —— 那等于让人自己猜。"""
        for o in B.run_all():
            if not o.ok:
                self.assertGreater(len(o.detail), 10, f"{o.case.id} 的失败说明太短")


class TestLoadBearing(unittest.TestCase):
    """基准集自己必须承重。

    一条用例只有在"把对应修复摘掉就会红"时才算数 —— 否则它只是把现状抄了一遍，
    将来引擎退化，它照样绿。这里用最小代价证明三处：CRLF、GBK、路径逃逸。
    （2026-10-20 实测：三处摘掉后对应用例全部变红。）
    """

    def _case(self, cid: str) -> B.Case:
        return next(c for c in B.CASES if c.id == cid)

    def test_去掉CRLF归一就红(self):
        with mock.patch.object(checks, "_norm", lambda t: t):
            self.assertFalse(B.run_case(self._case("B-file-06")).ok,
                             "CRLF 那条在没有归一化时仍然通过 —— 用例是摆设")

    def test_去掉GBK回退就红(self):
        with mock.patch.object(checks, "_decode", lambda b: b.decode("utf-8", "replace")):
            self.assertFalse(B.run_case(self._case("B-cmd-06")).ok,
                             "GBK 那条在没有编码回退时仍然通过 —— 用例是摆设")

    def test_去掉路径校验就红(self):
        with mock.patch.object(C, "_escape_reason", lambda p: ""):
            self.assertFalse(B.run_case(self._case("B-contract-04")).ok,
                             "绝对路径那条在没有校验时仍然通过 —— 用例是摆设")


if __name__ == "__main__":
    unittest.main()
