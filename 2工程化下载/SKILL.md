---
name: scansci-download
description: "本地化的 scansci-pdf 下载引擎封装：多源竞速、机构通道（Elsevier API / WebVPN / CARSI / EZProxy）、批量队列、引文导出与通道诊断。用于把已确定的 DOI / arXiv / 文献清单变成实际的 PDF。"
---

# 2工程化下载 —— 工程化下载引擎

这是 [Rimagination/scansci-pdf](https://github.com/Rimagination/scansci-pdf) 1.17.0 的**本地化封装**。
上游源码逐字快照在 `vendor/scansci-pdf/`，我们对它的必要修复以**显式补丁**存在。

**本目录不是独立技能**——它是 `paperforge` 的下载子能力。
上层路由与输出契约见 [../SKILL.md](../SKILL.md) 与 [../0路由/contract.md](../0路由/contract.md)。

---

## 什么时候用它

- 已经有 DOI / arXiv 号 / 文献清单，要把它们变成 PDF
- 需要走机构通道（付费墙论文）
- 需要诊断"为什么这篇下不下来"

什么时候**不要**用它：只有主题关键词、还没有确定文献列表时——先走
[../1学术查询/](../1学术查询/) 检索，那一步的输出才是这里的输入。

---

## 两条使用路径

### 通过本 skill 的流水线（推荐）

```bash
python 0路由/scripts/pipeline.py run --input <需求或清单>
```

流水线负责：输入归一化 → 元信息补全 → 去重 → 调用上游 batch → DOI 命名规范化
→ 合并同一 DOI 的多个副本 → 产出元信息表 / 日志 / 失败归因。

**直接调用上游不会做这些**，你会得到带来源后缀的中间文件、非 DOI 命名的文件名、
以及没有书目信息的空元信息表。

### 直接调用上游 CLI

```bash
<仓库>/workspace/.venv/Scripts/python -m scansci_pdf <子命令>
```

统一用 `python -m scansci_pdf`：不依赖 console script 在 PATH 上，
也不受 venv 是否激活影响。

常用子命令：

| 子命令 | 用途 |
|---|---|
| `get <DOI>` | 单篇下载 |
| `batch <文件>` | 批量（xlsx/csv/队列/APA/BibTeX 均可） |
| `fetch <DOI>` | 走 7 步机构级联（不走灰色源） |
| `search <词>` | 检索并落成队列文件 |
| `verify` / `resolve-oa` / `build-queue` | 标识符校验 / OA 定位 / 建队列 |
| `login --login-type webvpn\|carsi\|ezproxy` | 机构登录（需要可见浏览器） |
| `schools <关键词>` / `setup <学校>` | 查/配学校 |
| `elsevier-setup` / `elsevier-check` | Elsevier API Key 配置与实测 |
| `session-doctor` / `browser-status` / `browser-doctor` | 会话与浏览器诊断 |
| `config-cmd <键> [值]` | 读写配置 |
| `run` | 以 MCP stdio 服务器方式启动 |

---

## 我们的配置改动（与上游默认的差异）

全部由 `0路由/scripts/bootstrap.py` 写入 `workspace/scansci-pdf/config.json`：

| 配置项 | 上游默认 | 本 skill | 原因 |
|---|---|---|---|
| `output_dir` | `~/.scansci-pdf/papers` | `<仓库>/workspace/pdfs` | 契约要求所有 PDF 集中一个目录 |
| `cache_dir` | `~/.scansci-pdf/cache` | `<仓库>/workspace/scansci-pdf/cache` | 隔离在 skill 内，便于清理 |
| `auto_rename` | `true` | **`false`** | 上游会命名成「作者年份_标题」，**违反 DOI 命名契约** |
| `progress_bar_auto` | `true` | `false` | Agent 场景不要弹 GUI 悬浮窗 |
| `scihub_browser_headless` | `false` | `true` | 竞速浏览器无头，减少窗口闪烁 |
| `browser_headless` | `false` | `false` | 机构登录必须保留可见窗口 |
| `instsci_cookie_file` | 未设 | `<cache_dir>/instsci-cookies.json` | **见下方「必须配的一项」** |
| `batch_workers` / `request_delay_*` | 10 / 2–5 秒 | 按 `--profile` | 控制封 IP 风险 |

### 必须配的一项：`instsci_cookie_file`

上游把 WebVPN cookie 的**读写路径写成了两个不同的文件**：

- 登录写入（`browser_login.webvpn_login`）→ `<cache_dir>/instsci-cookies.json`
- 下载读取（`auth._get_cookie_path`）→ `<data_dir>/cookies/webvpn-cookies.json`

后果：登录成功，但下载永远报 `All saved cookies have expired.`，
**WebVPN 通道完全不可用**。`auth.py` 认 `instsci_cookie_file` 这个键，
配上它就能对齐两条路径——无需改上游源码。

---

## 补丁机制

`vendor/scansci-pdf/` 与上游**逐字一致**。我们对上游的必要修复全部放在
`patches/patches.json`，由 `scripts/apply_patches.py` 应用：

```bash
python 2工程化下载/scripts/apply_patches.py --check      # 看状态
python 2工程化下载/scripts/apply_patches.py              # 应用（幂等）
python 2工程化下载/scripts/apply_patches.py --revert     # 撤销
python 2工程化下载/scripts/apply_patches.py --only 0004  # 只处理一条
```

补丁用**字面替换**而非行号 diff：上游行号漂移不会导致错打；
上下文不匹配时报 `conflict` 而不是硬打。

**不打补丁的后果**（每条补丁的 `why` 字段有完整说明）：

| 补丁 | 不打会怎样 |
|---|---|
| `0001` | `browser-status` / `browser-doctor` 直接崩（`UnboundLocalError`） |
| `0002` `0003` | `browser_executable` 配置被忽略，只有 Edge 的机器登录必失败 |
| `0004` | **WebVPN 登录永远超时、cookie 不保存，机构通道完全不可用** |
| `0005` | 登录等待期零输出，用户以为程序卡死 |
| `0006` | `elsevier-check` 把「key 有效但无全文权益」误报成「无效 key」，误导用户去重新申请 key |

`bootstrap.py apply` 会自动应用补丁（第 5 步）。

---

## 上游的两个坑，本 skill 已加防护层

### 1. 竞速引擎的"迟到成功"会造成文件丢失

上游 `get` / `batch` 的竞速引擎会在**迟到的成功**上回报文件路径，而此时仍有其它源
在跑（上游日志原文：`Racing finished with 3 source(s) still running (waived)`）。
进程收尾时那份文件可能被一并带走——表现为 **`batch` 报成功、磁盘上却没有文件**。

实测单篇 `get` 走同一条链路能稳定落盘。因此 `0路由/scripts/download.py` 加了一层
**校验 + 单篇兜底**：凡"上游报成功但磁盘上没有文件"的条目，自动改走
`scansci-pdf get <DOI> --output <PDF_DIR>` 重取一次，并在 `channel` 上标出
`+get-fallback`，元信息表里如实可见。

### 2. 上游写两份结果文件，字段互补

| 文件 | 内容 |
|---|---|
| `batch_results.json` | 逐车道尝试的明细（**只有 error 文本**，且常常只是车道预检那一行） |
| `download_results.json` | 规范化结果，带 **`error_type` / `reason` 结构化字段** |

只读前者会把归因做成一堆关键字匹配，并丢掉上游已经算好的终判。
本 skill 两份都读并合并，`detail` 里保留全部原始证据（见 `failures.md` 的「原始信息」列）。

### 3. `elsevier-check` 的画像判定过于武断

它只给两条出路：拿到 `ENTITLED` → 「广覆盖机构 key」；否则若 OA 对照也不通过
→ 一律判「无效 key」。但实测：不带 key 请求全文端点得到
`406 INVALID_INPUT (Accept: application/pdf is restricted)`，而带一个**有效但无该资源权益**
的 key 得到 `403 AUTHENTICATION_ERROR`——两者响应不同，说明 key 被正常识别了。
补丁 `0006` 补上「key 有效但无全文权益」这一档，并明确告诉用户
**重新申请 key 不会改变这个结果**。

---

## 安装

```bash
# 完整安装（建 venv + 装上游 + 打补丁 + 固化配置）
python 0路由/scripts/bootstrap.py apply --email <邮箱> --school <学校> --browser
```

两种来源，用 `--source` 切换：

| 来源 | 命令 | 特点 |
|---|---|---|
| `vendor`（默认） | `--source vendor` | 本地快照，离线可复现，走纯 Python 回退实现 |
| `pypi` | `--source pypi` | 装上游最新版，含预编译核心（README 称性能略优），需联网 |

### 关于 `_core` 专有层

上游 `src/scansci_pdf/_core/` 下的 Cython 编译扩展（`.pyd`/`.so`）是预编译二进制，
其 Cython 源码（`.pyx`）为专有代码、**不在上游仓库中**，因此也不在本副本中。
本副本走**纯 Python 回退实现**，上游称功能相同、性能略低。
想要编译核心就改用 `--source pypi`。

许可与归属见 [../NOTICE](../NOTICE) 与 [LOCALIZATION.md](LOCALIZATION.md)。

---

## 上游更新

```bash
# 1) 重新拉取上游快照覆盖 vendor/（会覆盖本地改动——所以本地改动必须都在补丁里）
# 2) 重新应用补丁，看是否报 conflict
python 2工程化下载/scripts/apply_patches.py --check
# 3) 若报 conflict：人工核对上游该处代码，更新 patches/patches.json 的 find/replace
# 4) 更新 PROVENANCE.json 里的 pinned commit
```

---

## 合规

本引擎聚合多条下载通路，其中 Sci-Hub / LibGen 类灰色源的可用性取决于
**司法辖区、机构授权与出版商条款**。策略档位由 `0路由/scripts/policy.py` 管理，
详见 [../0路由/policy.md](../0路由/policy.md)。

上游参考文档：`vendor/scansci-pdf/README.md`（完整配置表、机构通道、故障排查）、
`vendor/scansci-pdf/docs/PLAYBOOK.md`（反爬/镜像相关的工程约定）。
