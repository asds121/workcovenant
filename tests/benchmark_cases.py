# -*- coding: utf-8 -*-
"""基准集 —— 四类判据的**失败模式目录**。

和普通单测的区别：单测证明"这样能过"，基准集证明"这样**必须不过**"。
每一条都是一个真实会发生的破法（超时的命令、GBK 的输出、CRLF 的文件、
代码块里写着示例链接、绝对路径想读到仓库外面去……），
期望值写死在这里，跑一遍就知道引擎还认不认得出来。

跑：`python tools/benchmark.py`（矩阵） 或 `python -m unittest tests.test_benchmark -q`
"""
from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C      # noqa: E402
from wvc import score as S         # noqa: E402


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    title: str
    why: str
    build: Callable[[Path], dict]
    states: dict[str, str] = field(default_factory=dict)   # 判据 id → 期望状态
    exit_code: int | None = None
    verdict: str = ""
    error: str = ""                                        # 期望 ContractError 片段


@dataclass
class Outcome:
    case: Case
    report: S.Report | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.detail

    @property
    def detail(self) -> str:
        """空串 = 符合预期；否则是"差在哪"。"""
        c = self.case
        if c.error:
            if not self.error:
                return f"{c.id} 期望契约被拒绝，实际加载成功"
            if c.error not in self.error:
                return f"{c.id} 报错里没有 {c.error!r}：{self.error}"
            return ""
        if self.error:
            return f"{c.id} 契约没加载成功：{self.error}"
        rep = self.report
        assert rep is not None
        for cid, want in c.states.items():
            got = _state(rep, cid)
            if got != want:
                return f"{c.id} {cid} 期望 {want}，实际 {got}｜{_ev(rep, cid)}"
        if c.exit_code is not None and rep.exit_code != c.exit_code:
            return f"{c.id} 退出码期望 {c.exit_code}，实际 {rep.exit_code}"
        if c.verdict and c.verdict not in rep.verdict:
            return f"{c.id} 结论期望含 {c.verdict!r}，实际 {rep.verdict!r}"
        return ""


def _state(rep: S.Report, cid: str) -> str:
    for row in rep.rows:
        for crit, res in row.results:
            if crit.id == cid:
                return res.state
    return "缺失"


def _ev(rep: S.Report, cid: str) -> str:
    for row in rep.rows:
        for crit, res in row.results:
            if crit.id == cid:
                return res.evidence
    return ""


# ------------------------------------------------------------------ 小工具
def _c(cid: str, kind: str, title: str = "", **kw) -> dict:
    d = {"id": cid, "title": title or cid, "kind": kind,
         "why": "基准集：这一类错了必须被认出来"}
    d.update(kw)
    return d


def _doc(*cris: dict) -> dict:
    return {
        "format": C.FORMAT, "id": "bench", "name": "基准集用例", "profession": "基准",
        "version": "1.0.0", "owner": "benchmark",
        "requirements": [{"id": "R1", "title": "基准", "verbatim": "基准集用例",
                          "loop": ["跑一次"], "criteria": list(cris)}],
    }


def _write(root: Path, name: str, data: str | bytes) -> None:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


# ------------------------------------------------------------------ cmd（8）
def _cmd_cases() -> list[Case]:
    ok = _c("C1", "cmd", run='{python} -c "print(123)"', expect={"stdout_contains": "123"})
    code = _c("C1", "cmd", run='{python} -c "raise SystemExit(7)"')
    out = _c("C1", "cmd", run='{python} -c "print(1)"', expect={"stdout_contains": "2"})
    missing = _c("C1", "cmd", run="wvc_no_such_command_xyz_123")
    slow = _c("C1", "cmd", run='{python} -c "import time;time.sleep(3)"', timeout=1)
    gbk = _c("C1", "cmd", run='{python} -c "import sys;sys.stdout.buffer.write(\'中文输出\'.encode(\'gbk\'))"',
             expect={"stdout_contains": "中文输出"})
    err = _c("C1", "cmd", run='{python} -c "import sys;sys.stderr.write(\'炸了\')"',
             expect={"stderr_contains": "炸了"})
    crlf = _c("C1", "cmd", run='{python} -c "print(\'A\\r\\nB\')"',
              expect={"stdout_contains": "A"})
    return [
        Case("B-cmd-01", "cmd", "退出码 0 且输出命中", "最普通的一条必须过", lambda r: _doc(ok),
             {"C1": "pass"}, 0, "通过"),
        Case("B-cmd-02", "cmd", "非零退出码要红", "命令失败却记成过，是验收最常见的假绿",
             lambda r: _doc(code), {"C1": "fail"}, 1),
        Case("B-cmd-03", "cmd", "输出不含期望片段要红", "退出码 0 不等于做对了",
             lambda r: _doc(out), {"C1": "fail"}, 1),
        Case("B-cmd-04", "cmd", "命令不存在要红", "拼错命令不能变成「跳过」",
             lambda r: _doc(missing), {"C1": "fail"}, 1),
        Case("B-cmd-05", "cmd", "超时要红（可按判据配）", "卡住的命令必须自己结束，不能挂住整轮验收",
             lambda r: _doc(slow), {"C1": "fail"}, 1),
        Case("B-cmd-06", "cmd", "GBK 中文输出照样能断言", "中文 Windows 的控制台输出常是 GBK",
             lambda r: _doc(gbk), {"C1": "pass"}, 0, "通过"),
        Case("B-cmd-07", "cmd", "stderr 断言", "只看 stdout 会漏掉把错误写到 stderr 的程序",
             lambda r: _doc(err), {"C1": "pass"}, 0, "通过"),
        Case("B-cmd-08", "cmd", "输出带 CRLF 不影响匹配", "Windows 下换行是 CRLF，不该因此判红",
             lambda r: _doc(crlf), {"C1": "pass"}, 0, "通过"),
    ]


# ------------------------------------------------------------------ file（7）
def _file_cases() -> list[Case]:
    def has(root: Path) -> dict:
        _write(root, "a.md", "# 标题\n" + "内容" * 50)
        return _doc(_c("C1", "file", path="a.md"))

    def none(root: Path) -> dict:
        return _doc(_c("C1", "file", path="nope.md"))

    def tiny(root: Path) -> dict:
        _write(root, "a.md", "x")
        return _doc(_c("C1", "file", path="a.md", min_bytes=100))

    def hit(root: Path) -> dict:
        _write(root, "a.md", "# 标题\n正文\n")
        return _doc(_c("C1", "file", path="a.md", contains=r"^# 标题$"))

    def miss(root: Path) -> dict:
        _write(root, "a.md", "正文\n")
        return _doc(_c("C1", "file", path="a.md", contains=r"^# 标题$"))

    def crlf(root: Path) -> dict:
        _write(root, "a.md", b"# \xe6\xa0\x87\xe9\xa2\x98\r\nkey: value\r\n")
        return _doc(_c("C1", "file", path="a.md", contains=r"^key: value$"))

    def gbk(root: Path) -> dict:
        _write(root, "a.md", "中文内容".encode("gbk"))
        return _doc(_c("C1", "file", path="a.md", contains="中文内容"))

    return [
        Case("B-file-01", "file", "文件在", "最普通的一条", has, {"C1": "pass"}, 0),
        Case("B-file-02", "file", "文件不在是红不是灰", "交付物没交 ≠ 没验；混成灰就等于放行",
             none, {"C1": "fail"}, 1),
        Case("B-file-03", "file", "太小 = 空壳", "占位文件骗过 min_bytes 之外的所有检查", tiny,
             {"C1": "fail"}, 1),
        Case("B-file-04", "file", "正则命中（含 ^ $ 锚点）", "锚点写对了才叫精确", hit,
             {"C1": "pass"}, 0),
        Case("B-file-05", "file", "正则不命中要红", "contains 只查「有没有」，不能永远为真", miss,
             {"C1": "fail"}, 1),
        Case("B-file-06", "file", "CRLF 文件也能用 $ 锚点", "Windows 检出的文件是 CRLF，`$` 会撞上 \\r",
             crlf, {"C1": "pass"}, 0),
        Case("B-file-07", "file", "GBK 文件里的中文能匹配", "老系统导出的文本常不是 UTF-8", gbk,
             {"C1": "pass"}, 0),
    ]


# ------------------------------------------------------------------ links（8）
def _links_cases() -> list[Case]:
    def _root_for(root: Path, md: str, files: tuple[str, ...] = ()) -> dict:
        _write(root, "doc.md", md)
        for f in files:
            _write(root, f, "x")
        return _doc(_c("C1", "links", path="doc.md"))

    return [
        Case("B-links-01", "links", "正常相对链接", "基线",
             lambda r: _root_for(r, "[a](b.md)\n", ("b.md",)), {"C1": "pass"}, 0),
        Case("B-links-02", "links", "断链要红", "断链的文档假装有出处",
             lambda r: _root_for(r, "[a](nope.md)\n"), {"C1": "fail"}, 1),
        Case("B-links-03", "links", "带标题的链接", "`[a](b.md \"t\")` 很常见，别把标题当文件名",
             lambda r: _root_for(r, '[a](b.md "标题")\n', ("b.md",)), {"C1": "pass"}, 0),
        Case("B-links-04", "links", "尖括号空格路径", "`<my file.md>` 是合法的空格写法",
             lambda r: _root_for(r, "[a](<my file.md>)\n", ("my file.md",)), {"C1": "pass"}, 0),
        Case("B-links-05", "links", "URL 编码 %20", "带空格的文件被编码后要能还原",
             lambda r: _root_for(r, "[a](my%20file.md)\n", ("my file.md",)), {"C1": "pass"}, 0),
        Case("B-links-06", "links", "代码块里的示例链接要跳过", "文档里教一次写法就红一次，等于不可用",
             lambda r: _root_for(r, "```\n[a](不存在.md)\n```\n正文\n"), {"C1": "pass"}, 0),
        Case("B-links-07", "links", "引用式定义断了要红", "`[a]: b.md` 也指向文件，不能只看行内写法",
             lambda r: _root_for(r, "[a][x]\n\n[x]: nope.md\n"), {"C1": "fail"}, 1),
        Case("B-links-08", "links", "http / 锚点 / mailto 跳过", "外链不该被当成本地文件",
             lambda r: _root_for(r, "[a](https://x.y) [b](#sec) [c](mailto:someone) [d](tel:1)\n"),
             {"C1": "pass"}, 0),
    ]


# ------------------------------------------------------------------ manual（5）
def _manual_cases() -> list[Case]:
    def ev(root: Path, text: str | bytes | None) -> dict:
        if text is not None:
            _write(root, "e.md", text)
        return _doc(_c("C1", "manual", evidence="e.md"))

    return [
        Case("B-manual-01", "manual", "✅ 证据 → 过", "人工项的唯一通过方式",
             lambda r: ev(r, "✅ 看过了\n"), {"C1": "pass"}, 0),
        Case("B-manual-02", "manual", "❌ 证据 → 红", "人判红必须能传回引擎",
             lambda r: ev(r, "❌ 不行\n"), {"C1": "fail"}, 1),
        Case("B-manual-03", "manual", "没证据 → 灰", "没留证据就是没验，不是过",
             lambda r: ev(r, None), {"C1": "skip"}, 2),
        Case("B-manual-04", "manual", "有文件但没结论 → 灰", "空文件不能算看过了",
             lambda r: ev(r, "看了一遍，还行\n"), {"C1": "skip"}, 2),
        Case("B-manual-05", "manual", "带 BOM 的 ✅ 也认", "记事本存的是 UTF-8 BOM",
             lambda r: ev(r, "\ufeff✅ 看过了\n"), {"C1": "pass"}, 0),
    ]


# ------------------------------------------------------------------ contract（7）
def _contract_cases() -> list[Case]:
    def base() -> dict:
        return _doc(_c("C1", "cmd", run='{python} -c "print(1)"'))

    def no_why(root: Path) -> dict:
        d = base()
        del d["requirements"][0]["criteria"][0]["why"]
        return d

    def dup(root: Path) -> dict:
        d = base()
        d["requirements"][0]["criteria"].append(_c("C1", "file", path="a.md"))
        return d

    def manual_blocking(root: Path) -> dict:
        return _doc(_c("C1", "manual", evidence="e.md", blocking=True))

    def absolute(root: Path) -> dict:
        return _doc(_c("C1", "file", path="C:/Windows/win.ini"))

    def escape(root: Path) -> dict:
        return _doc(_c("C1", "file", path="../外面的文件.md"))

    def bad_timeout(root: Path) -> dict:
        return _doc(_c("C1", "cmd", run="x", timeout=0))

    def no_loop(root: Path) -> dict:
        d = base()
        d["requirements"][0]["loop"] = []
        return d

    return [
        Case("B-contract-01", "contract", "缺 why 要拒绝", "写不出守什么，就是「为了测而测」",
             no_why, error="why"),
        Case("B-contract-02", "contract", "判据 id 重复要拒绝", "同名判据会让报告指向两处",
             dup, error="重复"),
        Case("B-contract-03", "contract", "阻断项不许靠人留证", "一票否决权必须握在机器手里",
             manual_blocking, error="阻断"),
        Case("B-contract-04", "contract", "绝对路径要拒绝", "契约不能读到仓库外面去",
             absolute, error="绝对路径"),
        Case("B-contract-05", "contract", "`..` 逃逸要拒绝", "同上，换个写法也不行", escape, error=".."),
        Case("B-contract-06", "contract", "timeout 越界要拒绝", "0 秒超时会让所有命令类判据直接红",
             bad_timeout, error="timeout"),
        Case("B-contract-07", "contract", "没有闭环要拒绝", "没有闭环就没有验收", no_loop, error="loop"),
    ]


# ------------------------------------------------------------------ score（6）
def _score_cases() -> list[Case]:
    def two_pass(root: Path) -> dict:
        _write(root, "a.md", "# t\n")
        return _doc(_c("C1", "file", path="a.md"), _c("C2", "file", path="a.md"))

    def one_fail(root: Path) -> dict:
        _write(root, "a.md", "# t\n")
        return _doc(_c("C1", "file", path="a.md"), _c("C2", "file", path="nope.md"))

    def one_skip(root: Path) -> dict:
        _write(root, "a.md", "# t\n")
        return _doc(_c("C1", "file", path="a.md"),
                    _c("C2", "file", path="a.md", requires=["缺的料.txt"]))

    def blocked(root: Path) -> dict:
        _write(root, "a.md", "# t\n")
        return _doc(_c("C1", "file", path="nope.md", blocking=True), _c("C2", "file", path="a.md"))

    def fail_and_skip(root: Path) -> dict:
        _write(root, "a.md", "# t\n")
        return _doc(_c("C1", "file", path="nope.md"),
                    _c("C2", "file", path="a.md", requires=["缺的料.txt"]))

    def weighted(root: Path) -> dict:
        """两个需求：R1 1/2、R2 2/2 → (0.5+1)/2 = 75，需求等权。"""
        _write(root, "a.md", "# t\n")
        return {
            "format": C.FORMAT, "id": "bench", "name": "等权", "profession": "基准",
            "version": "1.0.0", "owner": "benchmark",
            "requirements": [
                {"id": "R1", "title": "一条红", "verbatim": "v", "loop": ["l"],
                 "criteria": [_c("A1", "file", path="a.md"), _c("A2", "file", path="nope.md")]},
                {"id": "R2", "title": "全过", "verbatim": "v", "loop": ["l"],
                 "criteria": [_c("B1", "file", path="a.md"), _c("B2", "file", path="a.md")]},
            ],
        }

    return [
        Case("B-score-01", "score", "全过 = 100 通过", "基线",
             two_pass, exit_code=0, verdict="通过"),
        Case("B-score-02", "score", "一条红 → 退出码 1", "未过必须让流水线停",
             one_fail, exit_code=1, verdict="未通过"),
        Case("B-score-03", "score", "只有灰 → 退出码 2", "2 不是通过",
             one_skip, exit_code=2, verdict="没验完"),
        Case("B-score-04", "score", "阻断红 → 不通过但保留分数", "抹成 0 会掩盖其它进展",
             blocked, exit_code=1, verdict="阻断项"),
        Case("B-score-05", "score", "红 + 灰 → 退出码 1", "一条红不能被一条灰盖掉",
             fail_and_skip, exit_code=1),
        Case("B-score-06", "score", "需求等权平均", "判据多的需求不许绑架总分",
             weighted, exit_code=1),
    ]


CASES: list[Case] = [*_cmd_cases(), *_file_cases(), *_links_cases(),
                     *_manual_cases(), *_contract_cases(), *_score_cases()]


def run_case(case: Case) -> Outcome:
    with tempfile.TemporaryDirectory(prefix="wvc_bench_") as d:
        root = Path(d)
        raw = case.build(root)
        p = root / "_contract.json"
        p.write_text(__import__("json").dumps(raw, ensure_ascii=False), encoding="utf-8")
        try:
            contract = C.load(p)
        except C.ContractError as exc:
            return Outcome(case, error=str(exc))
        return Outcome(case, report=S.evaluate(contract, root))


def run_all() -> list[Outcome]:
    return [run_case(c) for c in CASES]
