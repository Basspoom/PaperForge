# 部署关：首次使用前必须走一遍

`workspace/state/deploy.json` 里 `ready` 不为 `true` 时，**不要开始检索或下载**。
所有业务脚本都会用 `require_deployed()` 挡住你，并给出该跑哪条命令。

```bash
python 0路由/scripts/bootstrap.py check   # 只体检，不改动任何东西
python 0路由/scripts/bootstrap.py plan    # 打印将要做什么，等用户确认
python 0路由/scripts/bootstrap.py apply   # 执行
```

`apply` 是**幂等**的：失败后修掉问题重跑即可，不会重复破坏已有环境。

---

## apply 做了什么（顺序）

| # | 步骤 | 关键行为 |
|---|---|---|
| 1 | Python 3.12 | 优先用 `uv` 把解释器装进 `workspace/.uv-python`（不污染系统 Python） |
| 2 | venv | 在 `workspace/.venv` 建虚拟环境，逐级降级：`uv venv` → `python -m venv` → `python -m venv --without-pip` |
| 3 | pip | venv 里没有 pip 时：`ensurepip` → 仍失败则**直接从基础解释器复制 pip 目录**（纯文件操作，不触发子进程） |
| 4 | scansci-pdf | 从 `2工程化下载/vendor/scansci-pdf` 安装（`--source pypi` 可改为装上游最新版） |
| 5 | 上游补丁 | 跑 `2工程化下载/scripts/apply_patches.py`，把本地化副本的必要修复打上 |
| 6 | 隐身浏览器 | `--browser` 时安装 patchright（机构登录 / 过 Cloudflare 用） |
| 7 | 配置固化 | 写 `workspace/scansci-pdf/config.json`，见下 |
| 8 | 策略档位 | `--policy max\|legal` |
| 9 | 体检 | 跑 `doctor.py`，报告写进 `workspace/state/doctor.json` |
| 10 | 抄通性验收 | 真下 1 篇 OA 论文，确认整条链能通（`--skip-smoke` 可跳） |

---

## 常用参数

| 参数 | 说明 |
|---|---|
| `--email` | **强烈建议填**。OpenAlex 对匿名调用限速很严（常见 429），填了进礼貌池 |
| `--school` | 高校全称，配 WebVPN；`--no-school` 显式关闭 |
| `--proxy` | HTTP(S) 代理；不填则自动探测（见下） |
| `--elsevier-key` | Elsevier / ScienceDirect API Key，Elsevier 系论文从 15–30 秒降到 1–2 秒 |
| `--springer-key` | Springer Nature TDM Key |
| `--policy` | `max`（默认，能力最大化）/ `legal`（仅合法来源） |
| `--profile` | `safe` / `balanced`（默认）/ `aggressive`，控制并发与请求间隔 |
| `--browser` | 安装隐身浏览器后端（几百 MB，机构登录必需） |
| `--source` | `vendor`（默认，本地快照）/ `pypi`（上游最新版） |
| `--skip-install` | 只重新固化配置与策略，不动环境（排障时很有用） |
| `--skip-smoke` | 跳过抄通性验收 |
| `--interactive` | 交互式逐项询问 |

---

## 代理：自动探测

本机可能跑着 TUN/fake-ip 类代理（表现为 DNS 解析到 `198.18.x.x`）而没有设
`HTTP_PROXY` 环境变量。`doctor.py` 会：

1. 读环境变量（`HTTPS_PROXY` 等）
2. 读 Windows 系统代理设置（WinINET 注册表）
3. 扫常见本地端口：`7890 7891 7897 10809 10808 1080 1070 2080 2081 8889 8118 20171`

对候选逐个**实际转发一次 HTTPS 请求**来验证（只看端口开着不算数）。
探测结果写进 `doctor.json`，并在报告里给出建议。

> 判定细节：目标返回 4xx（尤其 429 限速）**算代理可用**——那恰恰证明链路是通的。

---

## 配置固化的内容

`apply` 会把这些写进 `workspace/scansci-pdf/config.json`：

| 配置项 | 值 | 为什么 |
|---|---|---|
| `output_dir` | `<仓库>/workspace/pdfs` | 契约要求所有 PDF 集中一个目录 |
| `cache_dir` | `<仓库>/workspace/scansci-pdf/cache` | 隔离在本 skill 内，便于清理 |
| `auto_rename` | **`false`** | 上游默认 `true` 会命名成「作者年份_标题」，**违反 DOI 命名契约** |
| `progress_bar_auto` | `false` | Agent 场景不要弹 GUI 悬浮窗 |
| `scihub_browser_headless` | `true` | 竞速浏览器无头，减少窗口闪烁 |
| `browser_headless` | `false` | 机构登录必须保留可见窗口 |
| `instsci_cookie_file` | `<cache_dir>/instsci-cookies.json` | **见下方「路径不一致」** |
| `batch_workers` / `request_delay_*` | 按 `--profile` | 控制封 IP 风险 |

### `instsci_cookie_file` 为什么必须设

上游把 WebVPN cookie 的**读写路径写成了两个不同的文件**：

- 登录写入（`browser_login.webvpn_login`）→ `<cache_dir>/instsci-cookies.json`
- 下载读取（`auth._get_cookie_path`）→ `<data_dir>/cookies/webvpn-cookies.json`

结果是「登录成功」但下载永远报 `All saved cookies have expired.`，
WebVPN 通道完全不可用。`auth.py` 认 `instsci_cookie_file` 这个键，
配上它就能对齐两条路径——**无需改上游源码**。

---

## 机构通道

### Elsevier / ScienceDirect API（推荐，无需浏览器）

1. 到 [dev.elsevier.com](https://dev.elsevier.com/) 创建应用，勾选
   **ScienceDirect Article Retrieval**（个人邮箱即可，免费）
2. `bootstrap.py apply --elsevier-key <KEY>`
3. 验证：`python -m scansci_pdf elsevier-check`

> **务必看懂 `elsevier-check` 的结论。** 它会给出四种画像，其中两种最容易被搞混：
>
> | 画像 | 含义 | 该做什么 |
> |---|---|---|
> | 广覆盖机构 key | 全文端点返回 200 | 什么都不用做，Elsevier 车道可用 |
> | **key 有效但无全文权益** | key 被 Elsevier 正常识别，但当前网络/账号没有 ScienceDirect 全文权益 | **在机构网络内重试**，或改用 OA / 机构通道（WebVPN）。**重新申请 key 不会改变结果** |
> | key 有效但无该刊订阅 | 部分刊能拿、部分不能 | 换刊或走机构通道 |
> | 无效 key | key 不被识别 | 才需要重新申请 |
>
> 区分依据（实测）：不带 key 请求全文端点 → `406 INVALID_INPUT`；
> 带一个有效但无权益的 key → `403 AUTHENTICATION_ERROR`；伪造 key → `503`。
> 上游原本把第二种误报成「无效 key」，本 skill 用补丁 `0006` 修正。

#### key 有效但拿不到全文时还有用吗

有。摘要/元数据端点**不需要订阅权益**，带 key 会返回更完整的字段
（含机构 affiliation）。所以 key 仍然值得配——只是不要把"配了 key"等同于
"Elsevier 论文就能秒下"。

### 高校 WebVPN

```bash
# 1) 配置学校（会同时写入 base_url）
python 0路由/scripts/bootstrap.py apply --school "中国科学技术大学" --skip-install --skip-smoke

# 2) 登录 —— 必须用普通终端（会弹出可见浏览器窗口）
python 0路由/scripts/bootstrap.py apply --browser        # 先装浏览器后端
<venv>/Scripts/python -m scansci_pdf login --login-type webvpn
```

登录流程：打开 WebVPN → 跳转学校统一身份认证 → **你在窗口里完成登录** →
程序自动检测并保存 cookie。等待上限 10 分钟，期间每 15 秒打印一次当前页面。

> ⚠️ **登录成功与否不是看有没有 cookie。** 实测发现网关在**登录之前**就会下发
> `wengine_vpn_ticket` cookie（同样 16 字符），据此判断会得到假阳性。
> 本 skill 的补丁改为**用网关真实探测一个经 WebVPN 转换过的 URL**，
> 只有不再被踢回登录页才算成功。

### CARSI / EZProxy

见上游文档 `2工程化下载/vendor/scansci-pdf/README.md` 的「机构通道」一节。

---

## 环境约束（真实踩过的坑）

### 1. Python ≥ 3.11

上游要求 `>=3.11`。系统只有 3.10 也没关系——`bootstrap` 会把 3.12 装进
`workspace/.uv-python`，所有业务脚本通过 `python -m pipeline` 自动切到 venv 解释器。

### 2. 受限沙箱 / 受限权限

浏览器相关功能在受限环境下会失败，报 `WinError 5 拒绝访问`。根因有两个：

| 现象 | 根因 |
|---|---|
| `Failed to start CloakBrowser` / `pipe(overlapped=...)` | Playwright 用 **Windows 命名管道**与浏览器驱动通信，沙箱禁止 |
| pip 安装报 `Permission denied` 写临时目录 | pip 需要写系统临时目录与用户缓存 |

**结论**：`bootstrap.py apply` 的安装步骤、以及任何浏览器操作，
需要在**普通终端**或**放宽文件权限**的环境下运行。
本 skill 已经把 `TMP`/`TEMP`/`SCANSCI_PDF_DATA_DIR`/`PLAYWRIGHT_BROWSERS_PATH`
等全部重定向进 `workspace/`（见 `_common.child_env()`），能减少但不消除这类限制。

### 3. arXiv 的 DOI 不在 Crossref

`10.48550/arXiv.*` 注册在 **DataCite**。纯 arXiv 清单进队时，
元信息补全必须走 arXiv Atom API 那一路，否则元信息表里只有标识符。

---

## 上游补丁机制

`2工程化下载/vendor/scansci-pdf/` 与上游**逐字一致**；我们对上游的必要修复
全部以显式补丁形式放在 `2工程化下载/patches/patches.json`，
由 `2工程化下载/scripts/apply_patches.py` 应用：

```bash
python 2工程化下载/scripts/apply_patches.py --check      # 看每条补丁的状态
python 2工程化下载/scripts/apply_patches.py              # 应用（幂等）
python 2工程化下载/scripts/apply_patches.py --revert     # 撤销
python 2工程化下载/scripts/apply_patches.py --only 0004  # 只处理一条
```

补丁用**字面替换**而不是行号 diff：上游行号漂移不会导致错打；
上下文不匹配时报 `conflict` 而不是硬打。

### 补丁清单

出问题时按这张表对照。每条补丁的完整说明（现象、根因、上游版本）在
`patches/patches.json` 的 `why` 字段里。

| ID | 文件 | 修复内容 | 不打会怎样 |
|---|---|---|---|
| `0001` | `browser_engine.py` | `_check_browser_backend()` 缺 `global` 声明 | `browser-status` / `browser-doctor` 直接抛 `UnboundLocalError` |
| `0002` | `browser_login.py` | `open_login_browser()` 漏传 `config` 给 `launch()` | 忽略 `browser_executable`，只有 Edge/非默认 Chrome 的机器**登录必失败** |
| `0003` | `browser_login.py` | `PersistentBrowser._start()` 同样漏传 `config` | 常驻会话同样忽略浏览器配置 |
| `0004` | `browser_login.py` | 给 `webvpn_login()` 补上**经网关实测的** `detect_login` | **WebVPN 登录永远等到超时、一个 cookie 都不存**，机构通道完全不可用 |
| `0005` | `browser_login.py` | 登录等待期每 15 秒打印当前页面 | 用户以为程序卡死（"转圈没反应"） |
| `0006` | `elsevier_check.py` | 区分「key 有效但无全文权益」与「无效 key」 | 把有效的 key 误报成无效，误导用户重新申请 |

> 补丁 `0004` 判定方式值得单独说明：**不能用"有没有 `wengine_vpn_ticket` cookie"
> 当判据**——实测发现网关在**登录之前**就会下发这个 cookie（同名同形态），
> 据此返回成功会保存一批无效 cookie，让后续所有机构请求都以为"会话有效"。
> 正确做法是用网关实测一个经 WebVPN 转换过的 URL，只有不再被踢回登录页才算成功。

### 上游的两个坑，本 skill 加了防护层

1. **竞速引擎的"迟到成功"会造成文件丢失**。`batch` 会在"迟到的成功"上回报文件路径，
   而此时仍有其它源在跑（上游日志：`Racing finished with 3 source(s) still running (waived)`），
   进程收尾时文件可能被一并带走——表现为**报成功却找不到文件**。
   `0路由/scripts/download.py` 做了校验 + 单篇 `get` 兜底重取。
2. **上游写两份结果文件**：`batch_results.json` 只有 error 文本（且常是车道预检那一行），
   `download_results.json` 才带结构化的 `error_type` / `reason`。两份都读并合并，
   归因才不会退化。

### 重新同步上游

```bash
# 1) 重新拉取上游快照覆盖 vendor/（会覆盖本地改动——所以本地改动必须都在补丁里）
# 2) 重新应用补丁，看是否报 conflict
python 2工程化下载/scripts/apply_patches.py --check
# 3) 若报 conflict：人工核对上游该处代码，更新 patches/patches.json 的 find/replace
# 4) 更新 PROVENANCE.json 里的 pinned commit
```

---

## 排障

| 现象 | 先做 |
|---|---|
| 说部署未通过 | `bootstrap.py check` 看哪项 FAIL |
| `scansci-pdf check` 报缺依赖 | `bootstrap.py apply --skip-smoke` 重装 |
| 下载报 `All saved cookies have expired.` | 检查 `instsci_cookie_file` 是否已配（见上） |
| 浏览器启动报 `WinError 5` | 换普通终端运行 |
| 登录窗口卡在转圈 | 终端会每 15 秒打印当前页面；看它是否已经跳回 WebVPN 门户 |
| OpenAlex 一直 429 | `bootstrap.py apply --email <你的邮箱> --skip-install --skip-smoke` |
| 下载很慢（Elsevier 系） | 配 `--elsevier-key` |
| 批量被出版商封 IP | `--profile safe` 重跑；等 24–48 小时或换出口 IP |
| 元信息表只有 DOI | `build_queue.py` 的补全被限速或源站未收录；看 `--no-enrich` 是否被误用 |
| 想确认整条链能通 | `bootstrap.py apply --skip-install`（会跑抄通性验收） |
