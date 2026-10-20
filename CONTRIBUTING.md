# 怎么贡献

这个仓库只有一条硬规矩：**改动必须能被判据证明。**

## 提 PR 之前，跑这四条

```bash
python tools/contract_check.py contracts/*.json   # 契约写全了没有
python tools/score.py contracts/仓库交付.json      # 质量门
python tools/score.py contracts/仓库治理.json      # 治理门（含敏感信息）
python tools/mutation_check.py                    # 引擎还咬不咬得住
```

四条全绿再提。**任何一条红了但你说"不影响"，请把那条判据改到能反映真实情况，而不是绕过它。**
判据和事实不符时，改判据、写清理由，是可以接受的贡献；关掉判据不行。

## 改契约要注意

- 加判据：必须写 `why`（守的是哪根红线）。写不出就是"为了测而测"。
- 改判据语义：`format` 版本的升级规则见 `docs/契约规范.md` §7，不许悄悄改。
- 新增职业契约：放进 `contracts/`，并保证 `contract_check.py` 能过；换职业只换判据内容。

## 不许提交的东西

- 真实客户的账务、票据、公司名、税号、账号、联系方式；
- 本机绝对路径（盘符接 Users 目录、/home 接家目录这类写法）；
- 任何形式的密钥、令牌、私钥。

推之前跑一次 `python tools/privacy_scan.py --tree --history`。
**历史删不干净** —— 一旦进了提交，改工作树是没用的。

## 提交信息

一句话说清"改了什么、为什么"。不要写"update"、"fix"。
