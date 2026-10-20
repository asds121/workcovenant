# -*- coding: utf-8 -*-
"""跑一份契约，出分数。

    python tools/score.py contracts/仓库交付.json
    python tools/score.py contracts/仓库交付.json --root . --only R1,R3
    python tools/score.py contracts/仓库交付.json --list       # 只列判据
    python tools/score.py contracts/仓库交付.json --json       # 给机器看

退出码
------
    0  全部判据通过
    1  有判据没过（含阻断项一票否决）
    2  没有未过，但有未验（缺料 / 没留证据）—— **2 不是通过**
    3  契约本身坏了（schema 不合法）—— 这种情况下一分都不该信

3 单独留一个码，是因为"契约写错了"和"事情没做好"必须分得开：
前者怪写契约的人，后者怪干活的人，混在一起就又变成甩锅。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C      # noqa: E402
from wvc import score as S         # noqa: E402

USAGE = """用法：python tools/score.py <契约.json> [选项]

  --root DIR     判据的工作目录（默认：仓库根）
  --only R1,R3   只跑这几条需求（调试用）
  --list         只列判据，不跑
  --json         输出 JSON（给 CI / 别的程序消费）
  -h, --help     看这段
"""


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if not args or {"-h", "--help"} & set(argv):
        print(USAGE)
        return 0 if args else 3
    path = args[0]
    root = ROOT
    only: set[str] | None = None
    for i, a in enumerate(argv):
        if a == "--root" and i + 1 < len(argv):
            root = Path(argv[i + 1]).resolve()
        if a == "--only" and i + 1 < len(argv):
            only = {x.strip().upper() for x in argv[i + 1].split(",") if x.strip()}

    try:
        c = C.load(path)
    except C.ContractError as exc:
        print(f"契约读不进来：\n{exc}", file=sys.stderr)
        return 3

    if "--list" in argv:
        for r in c.requirements:
            print(f"{r.id:<4} {r.title}")
            for crit in r.criteria:
                flag = "阻断" if crit.blocking else "    "
                print(f"     {flag} {crit.id:<8} [{crit.kind}] {crit.title}")
        return 0

    report = S.evaluate(c, root, only)
    print(S.dumps(report) if "--json" in argv else S.render(report))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
