# 策略档位：能力最大化 vs 仅合法来源

本 skill 聚合多条下载通路。其中 Sci-Hub / LibGen 类**灰色源**是否可用，取决于
**你所在司法辖区、你所在机构的订阅与授权、以及出版商条款**——这不是技术问题，
所以它被做成了一个显式的开关，而不是藏在默认值里。

---

## 两个档位

| 档位 | 上游配置 | 说明 |
|---|---|---|
| `max` | `scihub_enabled=true`、`download_strategy=fastest`、`use_tor_for_scihub=true` | **能力最大化**：灰色源全开，覆盖率最高。仅供本地能力验证，或在你有权获取相应内容时使用。 |
| `legal` | `scihub_enabled=false`、`download_strategy=legal_only`、`use_tor_for_scihub=false` | **仅合法来源**：OA 直链 / 预印本 / 出版商 API / 机构通道。公开仓库的推荐默认值。 |

> 注意区分两套名字：`max` / `legal` 是**本 skill 的档位名**；
> 上游 `download_strategy` 的合法取值是
> `fastest` / `scihub_first` / `scihub_only` / `grey_only` / `oa_first` / `legal_only`。
> 档位名与上游字段不是一回事，`policy.py` 负责映射。

---

## 用法

```bash
python 0路由/scripts/policy.py show        # 看当前档位与关键配置
python 0路由/scripts/policy.py set max     # 能力最大化
python 0路由/scripts/policy.py set legal   # 仅合法来源
python 0路由/scripts/policy.py set legal --dry-run   # 只打印将要改什么
```

档位写进 `workspace/scansci-pdf/config.json`，同时在
`workspace/state/config.json` 里记下 `policy` 与 `policy_applied_at`，
便于 `doctor.py` 与交付文档核对。

`bootstrap.py apply` 的 `--policy` 参数决定部署时用哪一档。

---

## 发布到公开仓库前必须做的事

本仓库交付的默认档位是 `legal`（**开放获取、出版社和机构授权来源**）。
如需在明确合规且有权获取的范围内进行本地实验，用户可以显式切换档位：

1. 运行 `python 0路由/scripts/policy.py set legal` 恢复安全默认
2. 只有用户明确确认并理解后果时，才使用 `policy.py set max`
3. 不要把 `max` 写入 Agent 的默认配置或自动化流程

`legal` 档位下起作用的通道：

| 通道 | 是否需要额外配置 |
|---|---|
| OA 直链（Unpaywall / OpenAlex / DOAJ / OpenAIRE） | 无 |
| 预印本（arXiv / bioRxiv / medRxiv） | 无 |
| 出版商 API（Elsevier ScienceDirect） | 需要 Elsevier API Key |
| 机构通道（WebVPN / CARSI / EZProxy） | 需要登录 |
| PMC / EuropePMC / CORE | 无 |

---

## 合规边界（写给使用者）

- 本工具**不授予任何内容访问权**。使用者必须自己有权获取所下载的内容。
- 请遵守你所在机构与出版商的使用条款，尤其是**批量下载**相关的限制。
- 机构出口 IP 通常是共享的：一个人触发风控，可能让整个网段被封。
  批量任务建议先把 `batch_workers` 调低、`request_delay` 拉大（见下）。
- 灰色源的可用性、域名与法律地位会变化；本 skill 不对其可用性做任何保证。

### 降低被封风险

```bash
# 稳妥档：并发 2，请求间隔 5–12 秒
python 0路由/scripts/bootstrap.py apply --profile safe --skip-install --skip-smoke
```

档位定义在 `bootstrap.py::PROFILES`：

| 档位 | `batch_workers` | 请求间隔 |
|---|---|---|
| `safe` | 2 | 5–12 秒 |
| `balanced` | 4 | 3–8 秒（默认） |
| `aggressive` | 10 | 2–5 秒 |
