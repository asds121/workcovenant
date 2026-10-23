# -*- coding: utf-8 -*-
"""锁检查 —— 每份契约与它的基线是否一致。

    python tools/lock_check.py --check     # 发布前的门：不一致就红
    python tools/lock_check.py --write     # 由人重新生成基线（会留下可见的 diff）

为什么要单独一个门：`blocking: true → false` 不会让任何判据变红，它只会让报告变好看。
一份能自己把自己放松的契约，比一份跑不动的契约更危险 —— 后者至少看得出来。

退出码：0 全部一致 / 1 有不一致（或锁文件缺失）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C      # noqa: E402
from wvc import lock as L          # noqa: E402

CONTRACTS = ROOT / "contracts"
CHANGELOG = ROOT / "CHANGELOG.md"


def lock_path(contract_path: Path) -> Path:
    """基线放在 `contracts/locks/` 子目录 —— 别让 `contracts/*.json` 把它当成契约。"""
    return contract_path.parent / "locks" / f"{contract_path.stem}.json"


def default_paths() -> list[Path]:
    return sorted(p for p in CONTRACTS.glob("*.json") if p.is_file())


def write(p: Path) -> str:
    c = C.load(p)
    lock = L.make(c)
    lp = lock_path(p)
    lp.parent.mkdir(parents=True, exist_ok=True)
    before = L.read(lp) if lp.is_file() else None
    # newline="\n" 不能省：Windows 默认会把锁文件写成 CRLF，而仓库锁死 LF（.gitattributes），
    # 结果每次 --write 都刷出一整个文件的 diff。
    lp.write_text(L.dumps(lock), encoding="utf-8", newline="\n")
    if before is None:
        return f"新建 {lp.relative_to(ROOT).as_posix()}"
    old = before.get("criteria", {})
    diff = [cid for cid in old if cid not in lock["criteria"]]
    diff += [cid for cid in lock["criteria"] if cid not in old]
    diff += [cid for cid in old
             if cid in lock["criteria"] and old[cid].get("fp") != lock["criteria"][cid]["fp"]]
    return f"重写 {lp.relative_to(ROOT).as_posix()}" + (f"（变动：{'、'.join(diff)}）" if diff else "（无变动）")


def check(p: Path, changelog: str) -> tuple[bool, str]:
    lp = lock_path(p)
    if not lp.is_file():
        return False, (f"❌ {p.name}：没有锁文件 {lp.relative_to(ROOT).as_posix()} —— "
                       "没有基线，「被禁用」根本无从发现")
    try:
        c = C.load(p)
    except C.ContractError as exc:
        return False, f"❌ {p.name}：{exc}"
    errs, notes = L.verify(c, L.read(lp), changelog)
    head = f"{'✅' if not errs else '❌'} {p.name} {c.version} · {len(c.criteria)} 条判据 · " \
           f"{len(c.blocking)} 条阻断"
    tail = [f"   · {n}" for n in notes] + [f"   ❌ {e}" for e in errs]
    return not errs, "\n".join([head, *tail])


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    paths = [Path(a) for a in args] or default_paths()
    paths = [p if p.is_absolute() else (Path.cwd() / p) for p in paths]
    if "--write" in argv:
        for p in paths:
            print("✅ " + write(p))
        return 0
    if "--check" not in argv:
        print(__doc__)
        return 3

    changelog = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.is_file() else ""
    ok_all = True
    for p in paths:
        ok, text = check(p, changelog)
        print(text)
        ok_all = ok_all and ok
    print("=" * 60)
    print("全部一致" if ok_all else "有契约与锁不一致 —— 先看差在哪，再决定是收紧还是放宽")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
