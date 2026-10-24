# -*- coding: utf-8 -*-
"""示例也要能被跑 —— 不然它只是贴在仓库里的一段文字。

`examples/最小契约/` 是给第一次接触的人看的：三条判据、三张单子、一次红。
它的两个数字（100 / 67）写在教程里，这里把它们钉住 —— 教程里的数字和 README 里的
体积是同一类东西：**说错了不会红，所以特别容易错。**
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C      # noqa: E402
from wvc import score as S         # noqa: E402

EXAMPLE = ROOT / "examples" / "最小契约"


def _raw(name: str) -> dict:
    return json.loads((EXAMPLE / name).read_text(encoding="utf-8"))


class TestMinimalExample(unittest.TestCase):
    def test_示例契约本身合格(self):
        self.assertEqual([], C.validate(_raw("报销单契约.json")))

    def test_示例跑出满分(self):
        rep = S.evaluate(C.load(EXAMPLE / "报销单契约.json"), ROOT)
        self.assertEqual(100, round(rep.overall))
        self.assertEqual(0, rep.exit_code)
        self.assertEqual("通过", rep.verdict)

    def test_改错一个金额就会红(self):
        """教程里说"改成 128.10 会得 67 分、退出码 1" —— 把这句话钉住。"""
        tmp = Path(tempfile.mkdtemp(prefix="wvc_example_", dir=ROOT))
        try:
            data = _raw("报销单.json")
            data["items"][0]["amount"] = 128.10
            (tmp / "报销单.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")

            raw = _raw("报销单契约.json")
            for req in raw["requirements"]:
                for c in req["criteria"]:
                    c["path"] = f"{tmp.name}/报销单.json"     # 相对仓库根，不是绝对路径
            (tmp / "契约.json").write_text(
                json.dumps(raw, ensure_ascii=False), encoding="utf-8")

            rep = S.evaluate(C.load(tmp / "契约.json"), ROOT)
            self.assertEqual(67, round(rep.overall))
            self.assertEqual(1, rep.exit_code)
            self.assertIn("E1-a", rep.verdict, "红必须指名到阻断项，不能只说'不通过'")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
