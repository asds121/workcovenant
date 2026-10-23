# -*- coding: utf-8 -*-
"""基准集矩阵 —— 四类判据的失败模式，一条一行。

    python tools/benchmark.py            # 全矩阵（给人看）
    python tools/benchmark.py --quiet    # 只留汇总（给契约判据调用）

和 `python -m unittest` 的分工：单测回答"这样能过"，基准集回答"这样**必须不过**"。
矩阵里每条红都直接写着"差在哪"，不用再去翻 traceback。

退出码：0 全部符合预期 / 1 有用例不符合。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import benchmark_cases as B      # noqa: E402

GROUP_NAME = {
    "cmd": "cmd：跑命令（退出码 / 输出 / 超时 / 编码）",
    "file": "file：看文件（在不在 / 够不够大 / 内容对不对 / CRLF）",
    "links": "links：查链接（断链 / 标题 / 空格 / 编码 / 代码块）",
    "manual": "manual：人工证据（✅ / ❌ / 没证据 / 空文件 / BOM）",
    "data": "data：一批记录（必填 / 禁词 / 超时 / 条件 / 同源 / 坏 JSON）",
    "contract": "contract：契约校验（缺字段 / 重复 / 逃逸 / 越界 / 字段名写错）",
    "score": "score：打分口径（等权 / 退出码 / 阻断否决）",
}


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    outs = B.run_all()
    bad = [o for o in outs if not o.ok]

    if not quiet:
        group = None
        for o in outs:
            if o.case.group != group:
                group = o.case.group
                print(f"\n{GROUP_NAME.get(group, group)}")
            mark = "✅" if o.ok else "❌"
            print(f"  {mark} {o.case.id:<14} {o.case.title}")
            if not o.ok:
                print(f"       {o.detail}")

    per = Counter(o.case.group for o in outs)
    ok = Counter(o.case.group for o in outs if o.ok)
    print()
    print(" · ".join(f"{g} {ok[g]}/{per[g]}" for g in per))
    print(f"基准集 {len(outs) - len(bad)}/{len(outs)} 符合预期"
          + ("· 全部符合" if not bad else ""))
    for o in bad:
        print(f"  ❌ {o.detail}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
