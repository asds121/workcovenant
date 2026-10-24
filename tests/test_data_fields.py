# -*- coding: utf-8 -*-
"""`data` 判据里写错的字段名，不许静默通过。

契约层有字段白名单，`blockng` 这类错字会被当场拒掉（评审 §2.2）。但**数据层没有白名单**：
判据写 `rechecked_by`，数据里叫 `recheck_by` —— 契约照常加载、判据照常显示，
`when` 永远不成立，于是它一次都不会红。

这不是假设。工程验收契约的 F2-a 第一版就是这么写的，七条判据里只有它一直是绿的。

所以这里补一条：**判据引用的每个字段，数据里至少要出现过一次。**
一个都没出现，只有两种解释 —— 名字写错了，或者这一列根本没收。两种都会让判据变成装饰。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C      # noqa: E402


def _fields_of(clause: dict) -> list[str]:
    """一个子句引用到的所有字段名。"""
    out: list[str] = []
    if "when" in clause:
        out.append(clause["when"]["field"])
    out += list(clause.get("required", []))
    out += list(clause.get("forbidden", {}).get("fields", []))
    for a, b in clause.get("compare", {}).get("pairs", []):
        out += [a, b]
    if "sla" in clause:
        out += [clause["sla"]["start"], clause["sla"]["end"]]
    return out


class TestDataFields(unittest.TestCase):
    def test_data_判据引用的字段都在数据里(self):
        bad: list[str] = []
        for path in sorted((ROOT / "contracts").glob("*.json")):
            contract = C.load(path)
            for req in contract.requirements:
                for c in req.criteria:
                    if c.kind != "data":
                        continue
                    raw = json.loads((ROOT / c.path).read_text(encoding="utf-8"))
                    items = raw["items"] if isinstance(raw, dict) else raw
                    keys: set[str] = set()
                    for item in items:
                        keys |= set(item)
                    for clause in c.asserts:
                        for field in _fields_of(clause):
                            if field not in keys:
                                bad.append(f"{path.name} {c.id} → {field}")
        self.assertEqual([], bad,
                         "这些字段在数据里一次都没出现，判据会静默跳过（多半是字段名写错）："
                         + "; ".join(bad))


if __name__ == "__main__":
    unittest.main()
