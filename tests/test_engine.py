# -*- coding: utf-8 -*-
"""引擎自测 —— 钉住六条口径，改坏了当场红。

    python -m unittest discover -s tests -t . -q

为什么用 unittest 不用 pytest：这个仓库承诺**零依赖**。
要装东西才能验收的框架，验收本身会先被放弃。
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import mutation_check as M      # noqa: E402
from wvc import contract as C             # noqa: E402
from wvc import score as S                # noqa: E402


class Workspace:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wvc_test_")
        self.root = Path(self._tmp.name)
        (self.root / "doc.md").write_text(M.DOC, encoding="utf-8")
        (self.root / "evidence.md").write_text(M.EVIDENCE, encoding="utf-8")

    def run(self, raw: dict) -> S.Report:
        p = self.root / "_contract.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return S.evaluate(C.load(p), self.root)

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()


def state(report: S.Report, cid: str) -> str:
    for row in report.rows:
        for c, r in row.results:
            if c.id == cid:
                return r.state
    raise KeyError(cid)


class TestSchema(unittest.TestCase):
    def _load(self, raw: dict):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            return C.load(p)

    def test_两份真契约都合格(self):
        for name in ("仓库交付.json", "教培-能力契约.json"):
            c = C.load(ROOT / "contracts" / name)
            self.assertTrue(c.requirements, name)
            self.assertTrue(c.blocking, f"{name} 连一条阻断项都没有")

    def test_缺_why_要报错(self):
        raw = copy.deepcopy(M.BASE)
        del raw["requirements"][0]["criteria"][0]["why"]
        with self.assertRaises(C.ContractError) as ctx:
            self._load(raw)
        self.assertIn("why", str(ctx.exception))

    def test_id_重复要报错(self):
        raw = copy.deepcopy(M.BASE)
        raw["requirements"][0]["criteria"][1]["id"] = "R1-a"
        with self.assertRaises(C.ContractError) as ctx:
            self._load(raw)
        self.assertIn("重复", str(ctx.exception))

    def test_格式版本不对要报错(self):
        raw = copy.deepcopy(M.BASE)
        raw["format"] = "workcovenant.contract/0"
        with self.assertRaises(C.ContractError) as ctx:
            self._load(raw)
        self.assertIn("format", str(ctx.exception))

    def test_阻断项不许靠人留证(self):
        raw = copy.deepcopy(M.BASE)
        raw["requirements"][1]["criteria"][1]["blocking"] = True
        with self.assertRaises(C.ContractError) as ctx:
            self._load(raw)
        self.assertIn("阻断", str(ctx.exception))

    def test_没有闭环的契约不算数(self):
        raw = copy.deepcopy(M.BASE)
        raw["requirements"][0]["loop"] = []
        with self.assertRaises(C.ContractError) as ctx:
            self._load(raw)
        self.assertIn("loop", str(ctx.exception))


class TestScoring(unittest.TestCase):
    def test_基线全绿(self):
        with Workspace() as ws:
            rep = ws.run(M.BASE)
            self.assertEqual(rep.exit_code, 0, S.render(rep))
            self.assertEqual(rep.overall, 100)
            self.assertEqual(rep.verdict, "通过")

    def test_缺料进分母不算过(self):
        raw = copy.deepcopy(M.BASE)
        raw["requirements"][0]["criteria"][1]["requires"] = ["never.txt"]
        with Workspace() as ws:
            rep = ws.run(raw)
            row = rep.rows[0]
            self.assertEqual((row.passed, row.skipped, row.total), (1, 1, 2))
            self.assertEqual(row.ratio, 0.5)          # skip 进分母、不进分子
            self.assertEqual(rep.exit_code, 2)

    def test_未过比未验优先(self):
        """一条红 + 一条灰：退出码必须是 1，否则红会被灰盖掉。"""
        raw = copy.deepcopy(M.BASE)
        raw["requirements"][0]["criteria"][0]["min_bytes"] = 10 ** 6   # R1-a 红
        raw["requirements"][0]["criteria"][1]["requires"] = ["never.txt"]  # R1-b 灰
        with Workspace() as ws:
            rep = ws.run(raw)
            self.assertEqual(rep.exit_code, 1)
            self.assertEqual(rep.skipped, 1)

    def test_阻断项一票否决但保留分数(self):
        raw = copy.deepcopy(M.BASE)
        raw["requirements"][0]["criteria"][0]["min_bytes"] = 10 ** 6
        with Workspace() as ws:
            rep = ws.run(raw)
            self.assertTrue(rep.verdict.startswith("不通过"), rep.verdict)
            self.assertGreater(rep.overall, 0)

    def test_缺交付物是红不是灰(self):
        with Workspace() as ws:
            (ws.root / "doc.md").unlink()
            rep = ws.run(M.BASE)
            self.assertEqual(state(rep, "R1-a"), "fail")

    def test_断链要红(self):
        with Workspace() as ws:
            (ws.root / "doc.md").write_text(M.DOC + "\n[断的](nope.md)\n", encoding="utf-8")
            rep = ws.run(M.BASE)
            self.assertEqual(state(rep, "R2-a"), "fail")

    def test_按需求取平均(self):
        raw = copy.deepcopy(M.BASE)
        raw["requirements"][0]["criteria"][0]["requires"] = ["never.txt"]   # R1 → 1/2
        raw["requirements"][1]["criteria"] = raw["requirements"][1]["criteria"][:1]  # R2 → 1/1
        raw["requirements"][2]["criteria"][0]["expect"]["stdout_contains"] = "X"     # R3 → 0/1
        with Workspace() as ws:
            rep = ws.run(raw)
            self.assertAlmostEqual(rep.overall, (0.5 + 1.0 + 0.0) / 3 * 100, places=6)


class TestMutation(unittest.TestCase):
    def test_六条反证全咬住(self):
        self.assertEqual(M.main(["--quiet"]), 0)


if __name__ == "__main__":
    unittest.main()
