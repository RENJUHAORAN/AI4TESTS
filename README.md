# Codex + Playwright MCP 零代码 UI 测试 PoC

本仓库用 **Python** 实现零代码 UI 测试的确定性主体：

```text
自然语言测试卡
  -> 结构化 Test Contract
  -> Python 加载与 Schema/安全边界校验
  -> Python Playwright 确定性执行
  -> Trace、网络、控制台和失败证据
  -> Python 生成统一 result.json
```

Codex + Playwright MCP 负责探索、生成契约和失败分析；Python Playwright Runner 负责回归门禁。Node.js 仅作为 `@playwright/mcp@0.0.84` 的运行时，业务执行器和工程主体不依赖 JavaScript。

## 当前实现状态

截至 2026-11-03，已完成并实际验证：

- 35 个 pytest 用例通过，覆盖 Test Card 与 Contract 资产配对、`verify` 边界、结果 Schema、Codex 严格结构化输出、模板解析、URL 边界、脱敏、Playwright 新页面事件，以及源码/运行时/对账/流程目录/覆盖率发现链路。
- 六个中文项目 Skill 已通过 Skill Creator 校验，职责覆盖探索、编写、失败分析、源码清点、系统探索和流程对账。
- Python Playwright 成功登录闭环返回权威 `passed`，生成 Trace、网络和控制台证据。
- Python Playwright 预期失败闭环返回权威 `failed`，生成 Trace、截图、可访问性快照、网络和控制台证据。
- 浏览器缺失等基础设施异常返回 `blocked`，不冒充产品缺陷。
- Playwright MCP `0.0.84` 已完成真实导航和可访问性快照，`codex exec --output-schema` 已返回通过本地 Schema 校验的 `observed-pass` 结果。
- 发现流程默认只读，禁止 `allowMutations: true`，不同角色使用隔离浏览器上下文，并在写盘前校验发现结果 Schema。

本机没有修改全局 Codex 配置。烟测使用一次性 `-c mcp_servers.playwright=...` 注册；团队标准配置示例位于 `.codex/config.example.toml`。

## 快速开始

建议使用 Python 3.11 及以上版本：

```powershell
py -m pip install --user -e ".[dev]"
py -X utf8 -m pytest
```

安装后可直接通过模块入口调用 CLI（不依赖 Scripts 是否在 PATH）：

```powershell
py -X utf8 -m ui_test_poc.cli --help
```

如果用户级 Python Scripts 目录已在 PATH，也可以使用 `ui-test --help`。

运行确定性成功和失败演示：

```powershell
py -X utf8 scripts\run_demo.py
py -X utf8 scripts\run_failure_demo.py
```

也可以使用保留的 npm 薄入口，它们只会转调 Python：

```powershell
npm test
npm run test:demo
npm run test:demo:fail
npm run verify
```

可选的 MCP 端到端烟测：

```powershell
npm run test:mcp
```

该命令会按需启动 Python 示例站、一次性注册 Playwright MCP、调用 Codex、校验结构化结果和真实快照文件。它会调用模型并访问网络，因此不放入默认 `verify`。

## 系统流程发现

“最佳定位”不是只靠页面探索碰运气，而是把不同证据放到各自可靠的位置：

```text
前端源码 ----------> Source Graph（定义与入口）
Playwright --------> Runtime Graph（可达与角色差异）
XHR / fetch -------> Network Evidence（行为与依赖）
        \               /
         Python Reconciler
               |
     流程候选目录 + 覆盖缺口
               |
     Test Card -> Contract -> Runner
```

职责边界：

- 前端源码负责发现路由、页面、组件和导航定义。
- Playwright 负责验证页面在当前环境、当前角色下是否可达。
- 网络证据负责补充已观察的只读接口及其分类。
- Python 负责稳定 ID、图合并、去重、覆盖率、Schema 和产物落盘。
- AI 只做语义归纳、流程命名、风险提示和缺口解释。

这条链路不能承诺“发现 100% 业务流程”。它输出的是基于证据的候选目录、四类覆盖率和显式缺口；路由 `matched` 只表示源码与运行时对账成功，不代表业务断言通过。

分步执行：

```powershell
py -X utf8 -m ui_test_poc.cli discover source `
  --repo D:\work\frontend `
  --output artifacts\discovery\source

$env:APP_BASE_URL = "https://staging.example.com"
py -X utf8 -m ui_test_poc.cli discover runtime `
  --config discovery.yaml `
  --source-index artifacts\discovery\source `
  --output artifacts\discovery\runtime

py -X utf8 -m ui_test_poc.cli discover reconcile `
  --source artifacts\discovery\source `
  --runtime artifacts\discovery\runtime `
  --output artifacts\discovery

py -X utf8 -m ui_test_poc.cli discover catalog `
  --reconciliation artifacts\discovery `
  --output artifacts\discovery

py -X utf8 -m ui_test_poc.cli discover coverage `
  --reconciliation artifacts\discovery `
  --catalog artifacts\discovery `
  --output artifacts\discovery
```

串联执行：

```powershell
$env:APP_BASE_URL = "https://staging.example.com"
py -X utf8 -m ui_test_poc.cli discover all `
  --config discovery.example.yaml `
  --output artifacts\discovery\run-001
```

主要产物：

```text
manifest.json
source-graph.json
runtime-graph.json
reconciliation.json
process-catalog.json
coverage.json
pages.jsonl
transitions.jsonl
api-calls.jsonl
processes/*.yaml
snapshots/*.yml
```

四类覆盖率分别是 `routeCoverage`、`transitionCoverage`、`roleCoverage` 和 `processCoverage`。它们衡量证据覆盖，不等同于需求覆盖率或业务正确率。

本地只读演示：

```powershell
$env:PORT = "4173"
py -X utf8 examples\login_app\server.py

# 另一个终端
$env:APP_BASE_URL = "http://127.0.0.1:4173"
py -X utf8 -m ui_test_poc.cli discover all `
  --config discovery.local.example.yaml `
  --output artifacts\discovery-local
```

安全默认值：

- 页面导航和自动发现链接只访问 `target.allowedOrigins` 中的地址；浏览器的子资源加载仍依赖宿主网络出口控制。
- Playwright 路由层会中止非 GET/HEAD/OPTIONS 请求，并记录为被阻止的 mutation 证据。
- `allowMutations: true` 会在配置加载阶段直接失败。
- URL 查询参数、网络请求和快照进入证据前必须脱敏。
- 支付、退款、下单、删除、审批和权限变更必须由独立 Contract 与人工授权执行。

## Python 依赖与浏览器

核心依赖已声明在 `pyproject.toml`：

- `playwright`：确定性浏览器执行和证据采集。
- `PyYAML`：Test Contract 解析。
- `jsonschema`：Contract 和结果文档校验。
- `pytest`：工程单元测试，属于 `dev` 可选依赖。

如果本机尚未安装 Playwright 浏览器：

```powershell
py -m playwright install chromium
```

也可以复用已有浏览器缓存：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "F:\DevCache\playwright"
py -X utf8 scripts\run_demo.py
```

企业环境锁定浏览器版本时，使用 `PLAYWRIGHT_EXECUTABLE_PATH` 指向经过安全校验的 Chromium。Playwright 仍负责浏览器协议、等待和断言：

```powershell
$env:PLAYWRIGHT_EXECUTABLE_PATH = "C:\path\to\chrome.exe"
```

## 执行指定契约

原生 Python CLI：

```powershell
$env:WEB_BASE_URL = "https://staging.example.com"
$env:DEMO_USER = "test-user"
$env:DEMO_PASSWORD = "test-password"
py -X utf8 scripts\run_contract.py tests\contracts\LOGIN-001.yaml
```

通过 npm 薄入口执行：

```powershell
npm run test:contract -- tests/contracts/LOGIN-001.yaml
```

确定性 CLI 只接受 `mode: verify`。`explore` 契约只能由 Codex + Playwright MCP 执行，并输出 `observed-*` 结果，不能进入发布门禁。

### 移动端与多页面案例

`tests/contracts/JD-SEARCH-001.yaml` 是京东公开活动页的只读搜索回归案例：

```powershell
$env:JD_BASE_URL = "https://re.m.jd.com"
$env:PLAYWRIGHT_EXECUTABLE_PATH = "C:\path\to\chrome.exe"
py -X utf8 scripts\run_contract.py tests\contracts\JD-SEARCH-001.yaml
```

该契约演示了以下能力：

- `browser.viewport`、`isMobile`、`deviceScaleFactor`、`hasTouch` 和 `locale` 移动端上下文。
- `navigate`、`fill`、`click` 和跨标签页 `switchPage`。
- URL、标题、元素可见性和元素文本四类断言。
- `locator.nth` 指定同名元素中的第几个。

`switchPage` 必须在 Playwright 同步 API 中使用 `wait_for_timeout` 推进事件，不能使用 Python `time.sleep`；否则新标签页事件不会被调度。成功运行会生成 Trace、截图、可访问性快照、控制台和网络证据，并在 `result.json` 中给出权威 `passed`。

每次运行都在 `artifacts/runs/<run-id>/` 中生成证据和结果。运行结果版本字段包含：

```json
{
  "runner": "0.2.0",
  "python": "3.14.5",
  "playwright": "1.64.1",
  "contractSha256": "...",
  "environment": "local-demo"
}
```

真实项目应让契约声明自己的 `baseUrlRef` 和 Secret 环境变量，不要把生产凭据写入命令历史。

## 资产说明

- `tests/cards/`：中文自然语言测试卡，业务测试人员维护业务意图和验收结果。
- `tests/contracts/`：可校验、可回放的 Test Contract。
- `tests/fixtures/`：边界和负向测试夹具。
- `schemas/`：Contract、确定性结果和 MCP 观察结果 Schema。
- `src/ui_test_poc/contract.py`：加载、Schema 校验、Secret 引用和 URL 边界校验。
- `src/ui_test_poc/runner.py`：Python Playwright 确定性执行器和证据采集。
- `src/ui_test_poc/cli.py`：Python CLI。
- `src/ui_test_poc/discovery/`：源码索引、运行时探索、证据对账、流程目录和覆盖率。
- `examples/login_app/server.py`：Python 标准库本地示例站。
- `examples/discovery_frontend/`：用于验证源码路由提取的最小前端示例。
- `.codex/skills/`：中文 Codex Skills，用于探索、编写和失败分析；每个 Skill 的维护入口是其目录下的 `SKILL.md`。
- `.codex/config.example.toml`：固定版本 Playwright MCP 配置示例。

Test Card 与 Test Contract 按用例 ID 成对维护，并由 `tests/unit/test_test_assets.py` 自动检查。例如：

- `tests/cards/JD-SEARCH-001.yaml` 表达搜索业务的 Given/When/Then、数据引用和安全约束。
- `tests/contracts/JD-SEARCH-001.yaml` 固化定位器、动作、确定性断言和证据配置。

业务意图变化先改 Test Card；可执行步骤或断言变化再同步 Contract。不要只改 Contract 而遗漏 Test Card；缺少同 ID Card 时 pytest 会失败。

当前六个项目 Skill 的维护位置如下：

| Skill | 维护文件 | 职责 |
| --- | --- | --- |
| `ui-test-orchestrator` | `.codex/skills/ui-test-orchestrator/SKILL.md` | 使用 Playwright MCP 做只读探索、取证和观察结果输出 |
| `ui-test-authoring` | `.codex/skills/ui-test-authoring/SKILL.md` | 把 Test Card 转成可校验、可回放的 Test Contract |
| `ui-test-triage` | `.codex/skills/ui-test-triage/SKILL.md` | 基于证据做失败分类和定位修复建议 |
| `ui-source-inventory` | `.codex/skills/ui-source-inventory/SKILL.md` | 只读清点前端路由、页面入口和导航定义 |
| `ui-system-explorer` | `.codex/skills/ui-system-explorer/SKILL.md` | 按角色隔离、只读探索运行时页面和跳转 |
| `ui-process-cataloger` | `.codex/skills/ui-process-cataloger/SKILL.md` | 合并多源证据，生成流程候选和覆盖缺口 |

新增或修改 Skill 时，按系统 `skill-creator` 的规范更新对应 `SKILL.md`，再运行下文的 `quick_validate.py` 校验。不要只改提示词副本或在多个位置维护同一规则。

项目 Skill 建议使用中文提示词调用：

```text
使用 $ui-test-orchestrator，在 local-demo 环境执行 LOGIN-001 的 explore 模式。
只允许访问 http://127.0.0.1:4173，输出 observed 结果和证据，不要宣称正式通过。
```

源码与系统流程发现的中文调用示例：

```text
使用 $ui-source-inventory 只读清点 D:\work\frontend，
不安装依赖、不运行构建，输出带文件行号的路由证据。

使用 $ui-system-explorer 只读探索 staging，
匿名和普通用户各用独立上下文，遇到写操作停止。

使用 $ui-process-cataloger 对账上述证据，
输出流程候选和缺口，不要宣称流程完整或测试通过。
```

## Skill 校验

可以使用 Skill Creator 的官方校验器：

```powershell
py -m pip install --user PyYAML
$skillCreator = "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py"
py -X utf8 $skillCreator .codex\skills\ui-test-orchestrator
py -X utf8 $skillCreator .codex\skills\ui-test-authoring
py -X utf8 $skillCreator .codex\skills\ui-test-triage
py -X utf8 $skillCreator .codex\skills\ui-source-inventory
py -X utf8 $skillCreator .codex\skills\ui-system-explorer
py -X utf8 $skillCreator .codex\skills\ui-process-cataloger
```

Windows 中文环境需要 `-X utf8`；否则校验器可能按 GBK 读取中文 `SKILL.md` 并报编码错误。

## Codex / Playwright MCP

当前核验版本为 `@playwright/mcp@0.0.84`，生产环境不要使用 `@latest`。仓库烟测采用一次性注册，不修改全局配置：

```powershell
codex mcp add playwright -- npx -y "@playwright/mcp@0.0.84"
codex mcp get playwright --json
```

团队也可以参考 `.codex/config.example.toml` 注册。示例启用了隔离上下文、禁止 Service Worker、URL 参数脱敏和 origin allowlist；但 allowlist 不是完整网络安全边界。

非交互 `codex exec` 调用 MCP 时还需要 `--approve-for-me`，否则审批策略 `never` 会拒绝工具调用。该参数只应在隔离测试环境中使用。

完整架构、风险和落地路线见 [CODEX_PLAYWRIGHT_MCP_ZERO_CODE_SOLUTION.md](CODEX_PLAYWRIGHT_MCP_ZERO_CODE_SOLUTION.md)。

## 与 AI Agent 对话

有 Codex Skills 和 Playwright MCP 时，推荐先用中文探索，再生成契约：

```text
使用 $ui-test-orchestrator 和 Playwright MCP 只读探索以下页面。
目标 URL：https://re.m.jd.com/page/homelike?...
目标：验证公开搜索功能。
允许域名：re.m.jd.com、re.jd.com。
使用移动端视口，输入 ASCII 关键词 iPhone，提交搜索并切换到结果页。
不得登录、加购、下单或修改账户；不得使用 browser_evaluate。
只记录真实 Snapshot、工具步骤和候选断言，输出 observed 结果。
authoritativeStatus 必须为 null，不能声明正式通过。
```

探索结果经 `$ui-test-authoring` 转成 `mode: verify` 契约后，由本仓库 Python Runner 重新执行。只有 `result.json` 中的 `passed` 可以作为测试门禁结论。

公司内部的 CLI Agent 如果没有 MCP，可以执行 Shell 和读取仓库文件，推荐使用以下降级对话：

```text
你是只读 UI 测试执行 Agent。工作目录为当前仓库。
先读取 README.md、schemas/test-contract.schema.json 和
tests/contracts/JD-SEARCH-001.yaml，再执行：

$env:JD_BASE_URL="https://re.m.jd.com"
py -X utf8 -m pytest
py -X utf8 scripts/run_contract.py tests/contracts/JD-SEARCH-001.yaml

执行后读取最新 artifacts/runs/<run-id>/result.json。
只有 status=passed 才能说通过；failed 或 blocked 要引用失败步骤和证据文件。
不得为了让测试通过而删除断言或扩大 allowedOrigins。
不得登录、加购、下单、支付或修改账户。
```

如果内部 CLI Agent 支持 MCP 配置，优先注册固定版本的 Playwright MCP，并复用上面的探索提示词；如果完全不能调用浏览器，则把它当作“契约维护与结果解读 Agent”，不要让它凭截图猜测产品结论。
