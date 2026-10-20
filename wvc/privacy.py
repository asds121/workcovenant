# -*- coding: utf-8 -*-
"""敏感信息扫描 —— 公开仓库最贵的错误，是"以为删掉了"。

三条纪律
--------
1. **规则自带正反例**（`hits` / `misses`）：规则写歪了，自测当场红。
   一个只会说"干净"的扫描器，比没有扫描器更危险 —— 它给了一张假的体检报告。
2. **报告里不许出现明文**：命中值一律打码（前 2 后 2）。
   否则这份报告本身就是新的泄露源，而且会被贴进 issue。
3. **跳过的文件必须说出来**：二进制、超大文件不是"没扫到就算了"，
   它们会进 `skipped` 清单，由调用方决定要不要当失败。

为什么样例都写成相邻字面量拼接（`"gh" "p_..."`）：**扫描器不能扫到自己**。
如果规则文件里写着一条完整的假密钥，它自己就成了唯一的命中，
于是要么加豁免后门，要么永远红。拼接之后，源码里没有完整的敏感串，运行时才是。
"""
from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MAX_BYTES = 2 * 1024 * 1024          # 超过 2MB 的文件跳过（进 skipped 清单）
PROBE_BYTES = 8000                    # 用前 8KB 判二进制


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    pattern: str
    why: str
    allow: tuple[str, ...] = ()       # 命中值里出现这些，就不算（白名单）
    hits: tuple[str, ...] = ()        # 必须命中的样例
    misses: tuple[str, ...] = ()      # 必须不命中的样例


# 实体名用 \u 转义写：否则规则源码自己会被 P7 扫到（"有限公司"就躺在 pattern 里）。
_COMPANY = r"[\u4e00-\u9fa5]{2,}(?:\u6709\u9650\u8d23\u4efb\u516c\u53f8|\u80a1\u4efd\u6709\u9650\u516c\u53f8|\u6709\u9650\u516c\u53f8|\u4e8b\u52a1\u6240|\u7814\u7a76\u9662)"

RULES: tuple[Rule, ...] = (
    Rule(
        id="P1", name="统一社会信用代码 / 税号",
        pattern=r"(?:统一社会信用代码|纳税人识别号|税号|信用代码)[：:\s]*([0-9A-HJ-NPQRTUWXY]{18})",
        why="税号能直接定位到一家具体企业，是账套数据里最硬的身份标识",
        hits=("统一社会信用代码：" "91" "330100MA2XXXXX0X",),
        misses=("统一社会信用代码见附件",),
    ),
    Rule(
        id="P2", name="身份证号",
        pattern=r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)",
        why="个人身份信息一旦公开无法撤回，且与财务数据组合即可定位到人",
        hits=("110101" "19900307" "123X",),
        misses=("2026-10-20", "12511173.28"),
    ),
    Rule(
        id="P3", name="手机号",
        pattern=r"(?<![\d.])1[3-9]\d{9}(?![\d.])",
        why="联系方式属于个人信息；公开仓库里出现基本等于泄露",
        hits=("138" "0000" "1234",),
        misses=("192.168.1.100", "12,511,173.28"),
    ),
    Rule(
        id="P4", name="邮箱地址",
        pattern=r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        why="客户/同事邮箱不该出现在公开仓库；维护者邮箱只允许 GitHub noreply 形式",
        allow=(r"(?i)@users\.noreply\.github\.com$", r"(?i)@example\.(com|org)$",
               r"(?i)@apache\.org$"),
        hits=("zhangsan" "@" "qq.com",),
        misses=("asds121@users.noreply.github.com", "someone@example.com", "http://www.apache.org/licenses/"),
    ),
    Rule(
        id="P5", name="密钥 / 私钥 / 令牌",
        pattern=(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"
                 r"|\bgh[pousr]_[A-Za-z0-9]{36,}"
                 r"|\bsk-[A-Za-z0-9]{20,}"
                 r"|\bAKIA[0-9A-Z]{16}"
                 r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"),
        why="凭证泄露等于把仓库的写权限直接送人；历史上出现过就永远有效",
        hits=("-----BEGIN " "OPENSSH PRIVATE KEY-----",
              "gh" "p_" + "A" * 36,
              "sk" "-" + "b" * 24,
              "AKIA" + "Q" * 16),
        misses=("--- 分隔线", "sk- 这个前缀表示 OpenAI 密钥", "AKIA 是 AWS 的密钥前缀"),
    ),
    Rule(
        id="P6", name="本机绝对路径",
        pattern=r"[A-Za-z]:[\\/]{1,2}(?:Users|Documents and Settings)[\\/]|[A-Za-z]:[\\/]{1,2}\u4ee3\u7801[\\/]|/(?:home|Users)/[A-Za-z0-9._-]+/",
        why="绝对路径会泄露机器用户名、目录结构，也会让别人的机器跑不通",
        hits=("C:" "\\Users\\" "someone\\Documents", "D:" "\\\u4ee3\u7801\\" "proj"),
        misses=("/usr/local/bin", "docs/契约规范.md", "C:/Program Files"),
    ),
    Rule(
        id="P7", name="企业主体名",
        pattern=_COMPANY,
        why="客户公司全称是最典型的账套敏感信息，公开即违约",
        hits=("示例" "科技" "有限" "公司",),
        misses=("薄壳公司", "小团队", "第三方服务"),
    ),
    Rule(
        id="P8", name="银行账号",
        pattern=r"(?:账号|卡号|账户)[：:\s]*\d{10,}",
        why="银行账号 + 户名 = 一笔可发起的支付指令，比金额本身更敏感",
        hits=("账号：" "6222" "0202" "0001" "1112" "222",),
        misses=("账号见回单", "账户余额 12,511,173.28"),
    ),
)

_RE_CACHE: dict[tuple[str, str], re.Pattern] = {}
_ALLOW_CACHE: dict[tuple[str, tuple[str, ...]], tuple[re.Pattern, ...]] = {}


def _re(rule: Rule) -> re.Pattern:
    """按 (id, pattern) 缓存 —— **不能只按 id**。

    2026-10-20 踩过：反证把 P1 的 pattern 换成 `(?!)`，缓存按 id 取回了旧的编译结果，
    于是"规则改瞎"这条反证永远咬不住。缓存键必须包含被缓存的东西本身。
    """
    key = (rule.id, rule.pattern)
    if key not in _RE_CACHE:
        _RE_CACHE[key] = re.compile(rule.pattern)
    return _RE_CACHE[key]


def _allow_re(rule: Rule) -> tuple[re.Pattern, ...]:
    key = (rule.id, rule.allow)
    if key not in _ALLOW_CACHE:
        _ALLOW_CACHE[key] = tuple(re.compile(a) for a in rule.allow)
    return _ALLOW_CACHE[key]


@dataclass(frozen=True)
class Hit:
    rule_id: str
    rule_name: str
    path: str
    line_no: int
    value: str          # 已打码

    def line(self) -> str:
        return f"{self.path}:{self.line_no} · {self.rule_id} {self.rule_name} · {self.value}"


@dataclass
class ScanResult:
    files: int = 0
    commits: int = 0
    hits: list[Hit] = None            # type: ignore[assignment]
    skipped: list[str] = None         # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.hits = [] if self.hits is None else self.hits
        self.skipped = [] if self.skipped is None else self.skipped

    @property
    def ok(self) -> bool:
        return not self.hits


# ------------------------------------------------------------------ 扫描
def mask(s: str) -> str:
    s = s.strip()
    if len(s) <= 6:
        return "*" * len(s)
    return f"{s[:2]}***{s[-2:]}"


def scan_text(text: str, path: str = "<text>") -> list[Hit]:
    return _scan(text, path, RULES)


def _scan(text: str, path: str, rules: Iterable[Rule]) -> list[Hit]:
    out: list[Hit] = []
    for i, line in enumerate(text.splitlines(), 1):
        for rule in rules:
            m = _re(rule).search(line)
            if not m:
                continue
            val = m.group(1) if m.groups() else m.group(0)
            if any(a.search(val) for a in _allow_re(rule)):
                continue
            out.append(Hit(rule.id, rule.name, path, i, mask(val)))
    return out


def _tracked(root: Path) -> list[Path]:
    """已跟踪 **+ 未跟踪但未忽略** 的文件。

    只扫 `--cached` 是错的：发布前门要拦的是"你正要提交的东西"，
    而它此刻还在工作区里、尚未 `git add`（2026-10-20 实测漏掉三个新文件）。
    """
    try:
        raw = subprocess.run(["git", "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard"], cwd=str(root), capture_output=True,
                             check=True, timeout=60).stdout
        names = [n for n in raw.decode("utf-8", "replace").split("\0") if n]
        return [root / n for n in dict.fromkeys(names)]
    except (subprocess.SubprocessError, OSError):
        bad = {".git", "__pycache__", "node_modules", "out", ".venv"}
        return [p for p in root.rglob("*") if p.is_file() and not bad & set(p.parts)]


def scan_tree(root: str | Path) -> ScanResult:
    root = Path(root).resolve()
    res = ScanResult()
    for p in _tracked(root):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        size = p.stat().st_size
        if size > MAX_BYTES:
            res.skipped.append(f"{rel}（{size // 1024} KB，超过 {MAX_BYTES // 1024} KB）")
            continue
        blob = p.read_bytes()
        if b"\x00" in blob[:PROBE_BYTES]:
            res.skipped.append(f"{rel}（二进制）")
            continue
        res.files += 1
        res.hits.extend(scan_text(blob.decode("utf-8", "replace"), rel))
    return res


def _diff_path(line: str) -> str:
    """从 `+++ b/路径` 里取路径。

    中文文件名在 git 默认配置下会被写成 `"b/\\344\\270\\255..."`（八进制转义），
    直接切片会得到乱码，命中的**归因文件就错了**。
    这里同时兼容两种形态：命令里加了 `core.quotepath=false`，但读到老仓库时仍可能带引号。
    """
    raw = line[4:].strip()
    if raw == "/dev/null":
        return "<新增/删除>"
    if raw.startswith('"') and raw.endswith('"'):
        try:
            raw = ast.literal_eval(raw)
            # git 写的是「八进制转义的 UTF-8 字节」，literal_eval 之后是逐字节的 latin-1，
            # 要再拼回 UTF-8 才是原来的中文名；失败就保持原样（不是转义形态）。
            raw = raw.encode("latin-1").decode("utf-8")
        except (ValueError, SyntaxError, UnicodeEncodeError, UnicodeDecodeError):
            raw = raw.strip('"')
    return raw[2:] if raw.startswith("b/") else raw


def scan_history(root: str | Path) -> ScanResult:
    """扫**所有**提交的新增行 —— 公开仓库的历史删不干净，只能证明它从来是干净的。"""
    root = Path(root).resolve()
    res = ScanResult()
    cmd = ["git", "-c", "core.quotepath=false", "log", "-p", "--all", "--no-color",
           "--unified=0", "--pretty=format:__WC_COMMIT__%H"]
    try:
        raw = subprocess.run(cmd, cwd=str(root), capture_output=True, check=True,
                             timeout=180).stdout.decode("utf-8", "replace")
    except (subprocess.SubprocessError, OSError):
        res.skipped.append("（不是 git 仓库或读不到历史 —— 历史未扫）")
        return res

    commit, path, seen = "", "", set()
    for line in raw.splitlines():
        if line.startswith("__WC_COMMIT__"):
            commit = line[len("__WC_COMMIT__"):][:7]
            res.commits += 1
            continue
        if line.startswith("+++ "):
            path = _diff_path(line)
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for hit in scan_text(line[1:], path or "<diff>"):
            key = (hit.rule_id, hit.path, hit.value)
            if key in seen:
                continue
            seen.add(key)
            res.hits.append(Hit(hit.rule_id, hit.rule_name, f"{hit.path}@{commit}",
                                hit.line_no, hit.value))
    return res


# ------------------------------------------------------------------ 自测
def selftest(rules: Iterable[Rule] = RULES) -> list[str]:
    """每条规则必须咬住自己的正例、放过自己的反例。返回失败清单（空 = 通过）。

    `rules` 可传一份**改坏的**规则表（反证脚本就是这么用的）：
    规则退化成 `(?!)` 永远不命中时，这里必须立刻说出来，
    否则"扫描通过"只是规则失灵的同义词。
    """
    rules = tuple(rules)
    bad: list[str] = []
    for r in rules:
        for s in r.hits:
            got = [h.rule_id for h in _scan(s, "<sample>", rules)]
            if r.id not in got:
                bad.append(f"{r.id} 没咬住正例：{mask(s)}（实际命中 {got or '无'}）")
        for s in r.misses:
            got = [h.rule_id for h in _scan(s, "<sample>", rules)]
            if r.id in got:
                bad.append(f"{r.id} 误报了反例：{mask(s)}")
    return bad


def counts_by_rule(hits: Iterable[Hit]) -> dict[str, int]:
    out: dict[str, int] = {}
    for h in hits:
        out[h.rule_id] = out.get(h.rule_id, 0) + 1
    return out
