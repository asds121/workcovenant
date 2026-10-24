# -*- coding: utf-8 -*-
"""敏感信息扫描的自测 —— 证明它既不会漏，也不会冤。

两类错都致命：
- **漏**：假阴性的扫描器会让一次泄露带上"已检查"的章；
- **冤**：假阳性多的扫描器会被手动加白名单，直到白名单把真问题也放过。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import privacy as P      # noqa: E402

FAKE_KEY = "gh" "p_" + "Z" * 36          # 运行期才是真形状，源码里不是（否则扫描器扫到自己）
#: 「示例 / 某某」是**合成标记**，P7 已放行（2026-10-23）；植入用的名字必须长得像真的 ——
#: 否则这条判据验的是"示例会不会被抓"，而示例本来就不该被抓。
FAKE_COMPANY = "宏远" "贸易" "有限" "公司"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   cwd=str(repo), check=True, capture_output=True, timeout=60)


class TestRules(unittest.TestCase):
    def test_每条规则都有正反例(self):
        for r in P.RULES:
            self.assertTrue(r.hits, f"{r.id} 没有正例 —— 没人知道它到底能不能咬住")
            self.assertTrue(r.misses, f"{r.id} 没有反例 —— 没人知道它会不会乱咬")
            self.assertTrue(r.why.strip(), f"{r.id} 没写守着什么")

    def test_规则自测全过(self):
        self.assertEqual(P.selftest(), [])

    def test_规则不重复(self):
        ids = [r.id for r in P.RULES]
        self.assertEqual(len(ids), len(set(ids)))


class TestScan(unittest.TestCase):
    def test_命中会打码(self):
        text = "统一社会信用代码：" + "91330100MA2XXXXX0X"
        hits = P.scan_text(text)
        self.assertEqual(len(hits), 1)
        self.assertNotIn("91330100", hits[0].value, "报告里出现了明文 —— 报告本身成了泄露源")
        self.assertIn("***", hits[0].value)

    def test_白名单邮箱不冤(self):
        for ok in ("asds121@users.noreply.github.com", "someone@example.com"):
            self.assertEqual(P.scan_text(f"联系 {ok}"), [], ok)

    def test_普通邮箱要咬住(self):
        hits = P.scan_text("联系 zhangsan" "@" "qq.com")
        self.assertEqual([h.rule_id for h in hits], ["P4"])

    def test_扫描器扫自己(self):
        """规则文件里不该有完整的敏感串 —— 否则它自己就是唯一的命中。"""
        hits = P.scan_text((Path(ROOT) / "wvc" / "privacy.py").read_text(encoding="utf-8"),
                           "wvc/privacy.py")
        self.assertEqual(hits, [])

    def test_整个仓库干净(self):
        res = P.scan_tree(ROOT)
        detail = "\n".join(h.line() for h in res.hits)
        self.assertTrue(res.ok, f"工作树有 {len(res.hits)} 处命中：\n{detail}")


class TestNoFalseNegative(unittest.TestCase):
    """植入真东西，必须当场抓住 —— 这是"不漏"的唯一证明方式。"""

    def test_植入假密钥到工作树(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / "config.py").write_text(f'TOKEN = "{FAKE_KEY}"\n', encoding="utf-8")
            git(repo, "init", "-q")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "植入")
            res = P.scan_tree(repo)
            self.assertIn("P5", [h.rule_id for h in res.hits], "工作树里的假密钥没被抓住")

            # 删掉工作树里的文件，历史扫描仍必须抓住 —— 历史删不干净
            (repo / "config.py").unlink()
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "删除")
            self.assertTrue(P.scan_tree(repo).ok, "工作树应该已经干净")
            hist = P.scan_history(repo)
            self.assertIn("P5", [h.rule_id for h in hist.hits], "历史里的假密钥没被抓住")

    def test_植入企业名(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / "客户.md").write_text(f"客户：{FAKE_COMPANY}\n", encoding="utf-8")
            git(repo, "init", "-q")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "植入")
            self.assertIn("P7", [h.rule_id for h in P.scan_tree(repo).hits])

    def test_历史命中能归因到中文文件名(self):
        """中文路径在 git 里可能被转义；归因错了等于证据链断了。"""
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / "客户名单.md").write_text(f"客户：{FAKE_COMPANY}\n", encoding="utf-8")
            git(repo, "init", "-q")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "植入")
            (repo / "客户名单.md").unlink()
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "删除")
            hits = P.scan_history(repo).hits
            self.assertTrue(hits, "历史里的企业名没被抓住")
            self.assertIn("客户名单.md", hits[0].path, f"归因错了：{hits[0].path}")


if __name__ == "__main__":
    unittest.main()
