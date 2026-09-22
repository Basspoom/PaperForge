# LOCALIZATION — `2工程化下载/`

本目录 = **我方封装层** + **`vendor/scansci-pdf/` 上游快照**。

- 上游：`Rimagination/scansci-pdf`，整仓库逐字本地化到 `vendor/scansci-pdf/`，**未改任何源文件**。
- 我方的封装、安装脚本、配置覆盖与策略逻辑放在本目录（vendor 之外），
  以配置驱动而非打补丁的方式改变上游行为——这样上游可以整目录覆盖升级，不产生冲突。

因此本目录**不依赖运行时访问原仓库**，内容锚定在下面记录的 pinned commit 上。

## 1. 来源

| 项 | 值 |
|---|---|
| 上游仓库 | `https://github.com/Rimagination/scansci-pdf` |
| 版本 | `1.17.0`（`pyproject.toml` → `[project] version`） |
| 本地化目标目录 | `2工程化下载/vendor/scansci-pdf/` |
| 许可 | Apache License 2.0（`vendor/scansci-pdf/LICENSE`） |
| pinned commit | `9029cec266e4b821f31cf9ea81ef680a60b729d4` |
| commit 日期 | `2026-09-20T10:50:28Z` |
| Python 要求 | `requires-python >=3.11` |
| 入口点 | `scansci-pdf = "scansci_pdf.main:main"` |
| CLI 命令 | 22 个（`run` / `check` / `web` / `login` / `get` / `browser-status` / `browser-doctor` / `import-cookies` / `coverage` / `progress` / `setup` / `schools` / `fetch` / `batch` / `elsevier-setup` / `elsevier-check` / `session-doctor` / `federated-login` / `publisher-batch` / `search` / `plan` / `estimate` / `smoke` / `calibrate` / `verify` / `resolve-oa` / `build-queue` / `find` / `manifest` / `config-cmd`） |
| MCP 工具 | 17 个（上游 README「MCP 工具全表」） |
| 归属记录 | 仓库根 `NOTICE`、`PROVENANCE.json` |

MCP 启动方式：`scansci-pdf run`（stdio，默认），或 `scansci-pdf run --mode streamable_http --host 127.0.0.1 --port 8000`。

## 2. 本地化方式与排除项

整仓库逐字复制，**零源码改动**。复制时排除以下内容：

| 排除项 | 原因 |
|---|---|
| `*.pyd` | 预编译二进制扩展（Windows），属专有层分发物，不入库 |
| `*.so` | 预编译二进制扩展（Linux/macOS），同上 |
| `__pycache__/` | Python 字节码缓存，机器相关且可再生 |
| `*.pyc` | 同上 |
| `.git/` | 上游版本控制元数据；本仓库统一由根 `PROVENANCE.json` 记录来源 |

结果：`vendor/scansci-pdf/` 中不存在任何 `.pyd` / `.so` / `.pyx` 文件，
唯一保留的是纯 Python 源码、文档、配置模板与前端模板。

> 注：仓库根 `.gitignore` 已包含 `__pycache__/`、`*.py[cod]`、`*.pyd`、`*.so`，
> 因此即使本地运行产生字节码缓存，也不会进入版本库。

## 3. 专有 `_core` 层说明

**这一节决定了本 vendor 副本的能力边界，请务必读完。**

上游把代码分两层：

| 层 | 内容 | 许可与分发 |
|---|---|---|
| 公开层 | `src/scansci_pdf/**/*.py`、配置、文档、模板 | Apache License 2.0 |
| 专有层 | `src/scansci_pdf/_core/` 下的 Cython 编译扩展（`.pyd` / `.so`） | **仅通过 PyPI 分发**；其 Cython 源码（`.pyx`）为专有代码，**不在上游仓库中** |

由此推出三个事实：

1. `_core/` 的 Cython 源码（`.pyx`）**不在上游仓库中**，因此也**不在本 vendor 副本中**。
2. **GitHub 克隆与本 vendor 副本都走纯 Python 回退实现**。上游文档的措辞是：
   `GitHub 克隆使用纯 Python 回退实现（功能相同，性能略低）`。
   也就是说——能力不缺，慢一点。
3. **想要编译核心的用户应改为从 PyPI 安装**：`pip install scansci-pdf`。
   PyPI 分发包自带编译二进制。

在本 vendor 副本中，`src/scansci_pdf/_core/` 实际只剩 `__init__.py` 和 `.gitignore`，
这正是"排除构建产物"后的预期状态——不是复制漏了文件。

## 4. 两种安装模式

由环境变量 `SCANSCI_PDF_SOURCE` 切换（本 skill 的设计约定，不是上游配置项）：

| 项 | `SCANSCI_PDF_SOURCE=vendor`（默认） | `SCANSCI_PDF_SOURCE=pypi` |
|---|---|---|
| 安装来源 | 本目录 `vendor/scansci-pdf/`（`pip install -e` 本地路径） | `pip install scansci-pdf`（PyPI） |
| 是否联网 | 仅需依赖下载；上游代码离线可得 | 需要联网 |
| 可复现性 | **高**：代码锚定 pinned commit，不受上游发布影响 | 低：跟随最新发布版 |
| 核心实现 | 纯 Python 回退 | 含编译核心（`.pyd` / `.so`） |
| 性能 | 略低 | 略高 |
| 适用场景 | 默认；审计、离线、结果可复现、需要固定版本的场景 | 追求下载吞吐，或需要编译核心的场景 |

两种模式的**配置、CLI 与 MCP 工具面一致**，切换不改变调用方式。
本 skill 会把上游配置改造成下面第 5 节列出的值，无论走哪种模式都生效。

## 5. 本 skill 对上游配置的改动

配置文件：`$SCANSCI_PDF_DATA_DIR/config.json`（默认 `~/.scansci-pdf/config.json`）。
上游默认值取自 `src/scansci_pdf/config.py` 的 `DEFAULT_CONFIG`。

| 配置项 | 上游默认 | 我方默认 | 原因 |
|---|---|---|---|
| `output_dir` | `~/.scansci-pdf/papers` | `<skill>/workspace/pdfs` | 要求所有 PDF 集中到一个目录，便于交付与清点 |
| `cache_dir` | `~/.scansci-pdf/cache` | `<skill>/workspace/scansci-cache` | 缓存隔离在本 skill 内，不污染用户家目录、便于整体清理 |
| `auto_rename` | `true` | **`false`** | 硬性约束是 **DOI 命名**（`10.1038/nature12373` → `10.1038_nature12373.pdf`），必须关掉上游的 `作者年份_标题.pdf` 重命名 |
| `progress_bar_auto` | `true` | **`false`** | 避免在 Agent 场景弹出 GUI 悬浮进度窗；无人值守运行不接受窗口干扰 |
| `scihub_browser_headless` | `false` | `true` | 减少窗口闪烁；灰色源竞速全程零窗口 |
| `scihub_enabled` / `download_strategy` | `true` / `fastest` | 由 `0路由/scripts/policy.py` 统一管理 | 见下方策略表 |
| `batch_workers` / `request_delay_min` / `request_delay_max` | `10` / `2.0` / `5.0` | 由部署向导按档位写入 | 按"稳妥/激进"选择并发与延迟，见下方档位表 |

### 策略档位（`download_strategy` + `scihub_enabled`）

| 策略档 | `scihub_enabled` | `download_strategy` | 含义 |
|---|---|---|---|
| `max` | `true` | `fastest` | 灰色源开启，多源并行最快获胜。能力最大化，**仅用于本地能力验证与授权范围内的使用** |
| `legal` | `false` | `oa_first` | 关闭灰色源，优先开放获取。发布到公开仓库前必须切到这一档 |

切换命令：`python 0路由/scripts/policy.py set legal`（详见 `0路由/policy.md`）。
上游 `download_strategy` 的合法取值集合为
`fastest` / `scihub_first` / `scihub_only` / `grey_only` / `oa_first` / `legal_only`。

### 并发与延迟档位

| 档位 | `batch_workers` | `request_delay_min` | `request_delay_max` | 取向 |
|---|---|---|---|---|
| 稳妥 | 低（如 2） | 大（如 5） | 大（如 12） | 降低被出版商封 IP 的概率 |
| 激进 | 高 | 小 | 小 | 追求吞吐，接受更高封禁风险 |

上游默认（`10` / `2.0` / `5.0`）对应"偏激进"一侧；被封 IP 时上游的建议也是调低并发、拉大延迟
（见 `vendor/scansci-pdf/README.md` 的「批量调优」折叠块）。

## 6. 上游更新流程

1. 取上游新 commit 并记录 hash 与日期：

   ```bash
   git clone --branch main --single-branch https://github.com/Rimagination/scansci-pdf.git /tmp/scansci-pdf
   git -C /tmp/scansci-pdf checkout <new-commit>
   git -C /tmp/scansci-pdf show -s --format=%cI <new-commit>
   ```

2. 记录新版本号：`/tmp/scansci-pdf/pyproject.toml` → `[project] version`。

3. **整目录覆盖** vendor 副本，排除构建产物：

   ```bash
   rsync -a --delete \
     --exclude '__pycache__/' --exclude '*.pyc' \
     --exclude '*.pyd' --exclude '*.so' --exclude '.git/' \
     /tmp/scansci-pdf/ 2工程化下载/vendor/scansci-pdf/
   ```

   `--delete` 是刻意的：上游删除的文件必须在本地一并消失，否则会出现"幽灵模块"。

4. 复核二进制层：确认 `src/scansci_pdf/_core/` 下仍只有 `__init__.py` 与 `.gitignore`，
   且全目录无 `.pyd` / `.so` / `.pyx`。若上游改变了这套分层约定，第 3 节的说明需要重写。

5. 复核配置契约：比对新版 `config.py` 的 `DEFAULT_CONFIG` 与第 5 节表格，
   确认被本 skill 改写的每个 key 仍然存在、类型未变、语义未变（尤其 `auto_rename` 与 `download_strategy`）。`_VALID_STRATEGIES` 若有增删，策略档位表需同步。

6. 同步元数据（三处必须一致）：
   - `PROVENANCE.json` → `sources[1].pinned_commit` 与 `commit_date`（以及版本号若有独立记录）
   - `NOTICE` → 若排除项或专有层表述有变化
   - 本文档 → 第 1、2、3、5 节

7. 冒烟验证：`python 0路由/scripts/bootstrap.py check` → 真下 1 篇 OA 论文，
   确认 output_dir / DOI 命名 / 日志三项行为未变。

> 因为改动全部通过**配置**而非源码补丁实现，上游覆盖升级后不需要重放任何 diff。

## 7. 合规提示

本目录聚合了多条下载通路，其中部分通路（Sci-Hub / LibGen 类灰色源）是否可用取决于：

- **你的司法辖区**——灰色源在部分国家/地区受法律限制；
- **你所在机构的订阅授权**——机构通道（Elsevier API、WebVPN、CARSI、EZProxy）的有效性来自机构合同；
- **出版商条款**——批量抓取可能触发反爬与 IP 封禁，也可能违反使用条款。

必须明确的边界：

- **本工具不授予任何内容访问权。** 使用者须自行确保对所下载内容有合法获取权限。
- 本仓库交付的默认策略是**能力最大化**（`max`：灰色源开启），**仅用于本地能力验证与授权范围内的使用**。
- **发布到公开仓库前必须收紧默认**：`python 0路由/scripts/policy.py set legal`。
- 机构凭据、API key、cookie 只写本地配置与 `workspace/state/`，**永不写进仓库文件**，也不在回复中回显。
