# -*- coding: utf-8 -*-
"""锁的自测 —— 钉住"放松必须留下痕迹"。

    python -m unittest tests.test_lock -q

每一条都问同一个问题：**这次改动会让门槛变矮吗？** 会，就必须升版本并写进
CHANGELOG；不会（新增、收紧），就不该被拦。
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

from wvc import contract as C      # noqa: E402
from wvc import lock as L          # noqa: E402

RAW = {
    "format": C.FORMAT, "id": "lock-fixture", "name": "锁用最小契约", "profession": "测试",
    "version": "1.0.0", "owner": "锁自测",
    "requirements": [{
        "id": "R1", "title": "交付物在", "verbatim": "自测", "loop": ["跑一次"],
        "criteria": [
            {"id": "R1-a", "title": "文件够大", "why": "空壳等于没交", "kind": "file",
             "path": "doc.md", "min_bytes": 400, "blocking": True},
            {"id": "R1-b", "title": "有标题", "why": "没有标题读不懂", "kind": "file",
             "path": "doc.md", "contains": "^# "},
        ],
    }],
}


def build(raw: dict) -> C.Contract:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return C.load(p)


class TestLock(unittest.TestCase):
    def setUp(self) -> None:
        self.base = build(RAW)
        self.lock = L.make(self.base)

    def verify(self, raw: dict, changelog: str = "") -> list[str]:
        errs, _ = L.verify(build(raw), self.lock, changelog)
        return errs

    def test_原样通过(self):
        self.assertEqual(self.verify(RAW), [])

    def test_同版本降级阻断必须红(self):
        raw = copy.deepcopy(RAW)
        raw["requirements"][0]["criteria"][0]["blocking"] = False
        errs = self.verify(raw)
        self.assertTrue(errs, "阻断被降级，锁居然没说话")
        self.assertIn("R1-a", errs[0])
        self.assertIn("升版本", errs[0])

    def test_同版本删判据必须红(self):
        raw = copy.deepcopy(RAW)
        del raw["requirements"][0]["criteria"][1]
        errs = self.verify(raw)
        self.assertIn("R1-b", errs[0])

    def test_同版本改阈值必须红(self):
        raw = copy.deepcopy(RAW)
        raw["requirements"][0]["criteria"][0]["min_bytes"] = 100
        self.assertIn("R1-a", self.verify(raw)[0])

    def test_同版本新增也要红(self):
        """新增是收紧，但版本号必须跟着动 —— 否则没人知道契约变过。"""
        raw = copy.deepcopy(RAW)
        raw["requirements"][0]["criteria"].append(
            {"id": "R1-c", "title": "再来一条", "why": "自测", "kind": "file", "path": "doc.md"})
        self.assertIn("新增 R1-c", self.verify(raw)[0])

    def test_升版本但没写进_CHANGELOG_必须红(self):
        raw = copy.deepcopy(RAW)
        raw["version"] = "1.1.0"
        raw["requirements"][0]["criteria"][0]["blocking"] = False
        errs = self.verify(raw, changelog="这次只改了别的东西")
        self.assertTrue(any("R1-a" in e and "CHANGELOG" in e for e in errs), errs)

    def test_升版本并写进_CHANGELOG_才放行(self):
        raw = copy.deepcopy(RAW)
        raw["version"] = "1.1.0"
        raw["requirements"][0]["criteria"][0]["blocking"] = False
        self.assertEqual(self.verify(raw, changelog="放宽 R1-a：文档交付改由人工复核"), [])

    def test_改说明文字不必升版本(self):
        """`why` / `title` 不进指纹 —— 改措辞不改变判定。"""
        raw = copy.deepcopy(RAW)
        raw["requirements"][0]["criteria"][0]["why"] = "换一种说法，红线还是那根"
        self.assertEqual(self.verify(raw), [])

    def test_锁认错契约要红(self):
        lock = copy.deepcopy(self.lock)
        lock["contract"] = "别人家的契约"
        errs, _ = L.verify(self.base, lock)
        self.assertTrue(any("别人家的契约" in e for e in errs), errs)

    def test_空锁等于没锁(self):
        errs, _ = L.verify(self.base, {"format": L.FORMAT, "contract": self.base.id,
                                       "version": "1.0.0", "criteria": {}})
        self.assertTrue(any("空锁" in e for e in errs), errs)

    def test_真契约与锁一致(self):
        """仓库里的四份契约，锁都必须在且对得上 —— 这条挂了说明有人跳过了 --write。"""
        for p in sorted((ROOT / "contracts").glob("*.json")):
            lp = p.parent / "locks" / f"{p.stem}.json"
            self.assertTrue(lp.is_file(), f"{p.name} 没有锁文件")
            c = C.load(p)
            errs, _ = L.verify(c, L.read(lp), (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
            self.assertEqual(errs, [], f"{p.name}：" + "；".join(errs))


if __name__ == "__main__":
    unittest.main()
