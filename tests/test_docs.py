# -*- coding: utf-8 -*-
"""文档里的话也要能被机器核对：数字、版本、死链。

起因很具体，两条都不是笔误：
- README 一处写「55 条失败模式」，另一处写「41 条」；
- CHANGELOG 指向 `tests/test_units.py`，那个文件从来没存在过。

共同点：**没有人核对**。文档里的数字与路径，是这套框架最容易被当成"装饰"的部分，
也是唯一一处"说错了不会红"的地方 —— 补成一类判据，比再改一遍字更省事。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import benchmark_cases as B      # noqa: E402
from wvc import contract as C               # noqa: E402

DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "CHANGELOG.md"]
DOCS += sorted((ROOT / "docs").glob("*.md"))

PATH_REF = re.compile(r"`([A-Za-z0-9_./\-\u4e00-\u9fa5]+\.(?:py|md|json|yml|toml))`")
COUNT_REF = re.compile(r"(\d+)\s*(?:条|种)\s*失败模式")
MUT_REF = re.compile(r"(\d+)\s*条反证")
BROKE_REF = re.compile(r"改坏\s*(\d+)\s*次")
VERSION = re.compile(r"v(\d+\.\d+)")
READ_SIZE = re.compile(r"README\.md ([\d.]+) KB")

#: 这份文档描述的是**不在本仓库**的样板间（它自己第一段就写明了），
#: 里面 `tools/…`、`tests/…` 属于那边 —— 在这里判它死链，判的是一个本来就不该存在的文件。
EXEMPT = {"docs/样板间-会计.md"}


def _mutation_count() -> int:
    """反证条数以注册表为准，不数输出行。"""
    src = (ROOT / "tools" / "mutation_check.py").read_text(encoding="utf-8")
    return len(re.findall(r'^\s*\("M\d+', src, re.M))


class TestDocs(unittest.TestCase):
    def test_引用的仓库内路径都存在(self):
        missing = []
        for doc in DOCS:
            if doc.relative_to(ROOT).as_posix() in EXEMPT:
                continue
            for m in PATH_REF.finditer(doc.read_text(encoding="utf-8")):
                ref = m.group(1)
                if "/" not in ref or "*" in ref or "://" in ref:
                    continue
                if not (ROOT / ref).exists():
                    missing.append(f"{doc.relative_to(ROOT)} → {ref}")
        self.assertEqual([], missing, "文档引用了不存在的文件：" + "; ".join(missing))

    def test_失败模式条数处处一致(self):
        n = len(B.CASES)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        nums = {int(x) for x in COUNT_REF.findall(readme)}
        self.assertTrue(nums, "README 里没有提到失败模式条数")
        self.assertEqual({n}, nums, f"README 写的条数与基准集实际 {n} 条不符：{sorted(nums)}")

    def test_反证条数处处一致(self):
        n = _mutation_count()
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        nums = {int(x) for x in MUT_REF.findall(readme)}
        self.assertEqual({n}, nums, f"「N 条反证」与注册表 {n} 条不符：{sorted(nums)}")
        broken = {int(x) for x in BROKE_REF.findall(readme)}
        self.assertEqual({n}, broken, f"「改坏 N 次」与注册表 {n} 条不符：{sorted(broken)}")

    def test_预期输出里的体积是真的(self):
        """README 那段「预期输出」是承诺，不是装饰：它写多少 KB，就得是多少 KB。"""
        readme = ROOT / "README.md"
        want = f"{readme.stat().st_size / 1024:.1f}"
        m = READ_SIZE.search(readme.read_text(encoding="utf-8"))
        self.assertIsNotNone(m, "README 的预期输出里找不到 README 体积那一行")
        self.assertEqual(want, m.group(1),
                         f"README 实际 {want} KB，示例写的是 {m.group(1)} KB —— 改了 README 就顺手改这一行")

    def test_预期输出的表头与契约一致(self):
        """版本号、需求数、判据数都写在示例里 —— 加一条判据就会全错，所以钉住。"""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        m = re.search(r"仓库交付契约 ([\d.]+) · 通用（开源仓库）\n(\d+) 条需求 · (\d+) 条判据 "
                      r"· (\d+) 过 / (\d+) 没过 / (\d+) 没验", readme)
        self.assertIsNotNone(m, "README 的预期输出里找不到表头那一行")
        c = C.load(ROOT / "contracts" / "仓库交付.json")
        crits = sum(len(r.criteria) for r in c.requirements)
        self.assertEqual(c.version, m.group(1), "示例里的契约版本过时了")
        self.assertEqual(len(c.requirements), int(m.group(2)), "示例里的需求数过时了")
        self.assertEqual(crits, int(m.group(3)), "示例里的判据数过时了")
        self.assertEqual(crits, int(m.group(4)), "示例是全过的样子，过数必须等于判据数")
        self.assertEqual(0, int(m.group(5)))
        self.assertEqual(0, int(m.group(6)))

    def test_协议版本号两处一致(self):
        first = (ROOT / "docs" / "四角色协议.md").read_text(encoding="utf-8").splitlines()[0]
        doc_v = VERSION.search(first)
        self.assertIsNotNone(doc_v, "协议首行缺版本号")
        hits: set[str] = set()
        for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
            if "四角色协议" in line:
                hits |= set(VERSION.findall(line))
        self.assertEqual({doc_v.group(1)}, hits,
                         f"协议首行 v{doc_v.group(1)}，README 写的是 {sorted(hits)}")


if __name__ == "__main__":
    unittest.main()
