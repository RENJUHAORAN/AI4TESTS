# Codex + Playwright MCP 零代码 UI 自动化测试架构方案

## 1. 结论先行

这套方案可行，但“零代码”必须定义准确：

> **测试人员零脚本、零选择器、零框架代码；平台团队仍然需要建设测试契约、Skill、执行器、证据链和安全边界。**

推荐的目标形态不是“让 Codex 每次自由发挥地点页面”，而是：

1. 测试人员用自然语言、Given/When/Then 或 YAML 测试卡表达业务意图。
2. Codex 通过 Skill 把测试卡转换成结构化 Test Contract。
3. Codex + Playwright MCP 用于探索页面、生成契约、定位元素、采集证据和失败分析。
4. 可回归的用例由确定性 Playwright 执行器解释 Test Contract 执行。
5. 测试结论只来自确定性断言；Codex 的结论只能是 `observed-pass`、分析建议或修复建议。
6. 所有执行都产出可回放、可审计、可脱敏的证据包。

一句话架构：

> **Codex 负责理解和编排，Playwright MCP 负责浏览器交互和取证，Test Contract 负责可回归资产，确定性执行器负责回归门禁。**

### 1.1 当前 PoC 实现状态

截至 2026-11-03，本仓库已经落地以下可执行部分：

- 自然语言测试卡、Test Contract、Contract Schema 和 Run Result Schema。
- 六个中文 Skill：`ui-test-orchestrator`、`ui-test-authoring`、`ui-test-triage`、`ui-source-inventory`、`ui-system-explorer`、`ui-process-cataloger`。
- 原有三个测试 Skill 已通过 Codex App Server `skills/list` 实机发现；当前六个项目 Skill 均通过 Skill Creator 校验。
- 多源系统流程发现链路：前端源码清点、Playwright 只读运行时探索、证据对账、流程候选目录和分维度覆盖率。
- `discover source/runtime/reconcile/catalog/coverage/all` 分步与串联 CLI，以及 Source Graph、Runtime Graph、Reconciliation、Process Catalog 和 Discovery Manifest Schema。
- 页面导航与链接发现受 `target.allowedOrigins` 约束；非 GET/HEAD/OPTIONS 请求在 Playwright 路由层中止并记录为 mutation 证据。
- 只接受 `mode: verify` 的确定性 Playwright Runner，以及 Secret、origin 和结果 Schema 校验。
- 成功场景的权威 `passed`，失败场景的权威 `failed`，浏览器缺失等基础设施异常的 `blocked`。
- Trace、截图、可访问性快照、控制台和网络证据，以及流程发现快照、页面、跳转和 API JSONL 证据的统一落盘。
- 35 个 Python pytest 用例覆盖 Contract、状态边界、结果 Schema、Codex 严格结构化输出约束、中文 Skill、Runner 辅助逻辑和系统流程发现。
- 本地示例已用真实 Chromium 验证：2 条源码路由、2 个运行时页面、1 条跳转、2 条路由对账 `matched`，四类覆盖率均为 `1.0`。
- Playwright MCP 已完成真实 `browser_navigate` 和 `browser_snapshot`；`codex exec --output-schema` 已生成通过本地 Schema 校验的 `observed-pass` 结果和真实快照引用。

工程主体使用 Python 3.11+，包括 Contract 加载、JSON Schema 校验、Playwright Runner、系统流程发现、CLI、证据采集、结果校验和 pytest。Node.js 只保留为 `@playwright/mcp@0.0.84` 的必要运行时。本机没有修改全局 Codex 配置。烟测通过一次性 `-c mcp_servers.playwright=...` 注册 MCP，不覆盖用户配置；团队标准注册示例见 `.codex/config.example.toml`。`npm run test:mcp` 可重复执行该闭环，但因会调用模型和网络，不纳入默认 `verify`。

## 2. 研究基线

| 项目 | 结论 |
| --- | --- |
| Codex | 支持配置外部 MCP Server；`codex exec` 支持非交互执行、JSONL 事件和 JSON Schema 输出约束；project/user skills 可把测试流程固化为可复用能力。 |
| Playwright MCP | 通过 Playwright 的可访问性树与结构化工具操作页面，不依赖截图视觉模型；适合持久浏览器会话、探索式自动化、自愈建议和长链路代理流程。 |
| 适用边界 | Web 优先。移动端、Canvas、强视觉验收、性能测试不能直接等同于 Playwright MCP 能力。 |
| 关键限制 | MCP 会话是“代理执行”，不是天然可重复的 CI 测试资产；高频回归更适合确定性 Playwright/CLI；页面的可访问性树、截图、网络响应都属于不可信输入。 |

官方参考：

- Codex MCP: <https://developers.openai.com/codex/mcp>
- Codex Skills: <https://developers.openai.com/codex/skills>
- Playwright MCP: <https://github.com/microsoft/playwright-mcp>
- Playwright Test: <https://playwright.dev/docs/test-intro>

## 3. 零代码的边界

### 3.1 可以做到零代码的角色

- 业务测试人员不编写 Python、Playwright API、CSS/XPath。
- 测试人员通过自然语言修改测试意图和测试数据。
- 页面小改版时，由 Codex 产生定位修复建议，测试人员审核后更新契约。
- 失败后由 Codex 汇总证据、分类原因并生成缺陷摘要。

### 3.2 不能宣称零工程的环节

- MCP Server 的安装、版本锁定、代理和浏览器运行环境。
- Test Contract 的 Schema、执行器、断言库、数据管理和报告系统。
- 登录态、测试账号、验证码、MFA、SSO、测试数据清理。
- Prompt Injection、权限、网络出口、敏感信息和证据保留策略。
- 稳定性治理、误报率评估、模型升级回归和成本控制。

### 3.3 不应采用的形态

- 让 Codex 直接说“页面看起来正常，所以通过”。
- 每轮测试都重新生成脚本，没有版本化测试资产。
- 把 MCP 会话录像当作可重复回归用例。
- 业务断言失败后自动改写断言直到通过。
- 在无网络隔离、无操作审批、无审计记录的环境里自主执行破坏性操作。
- 用自然语言测试替代接口测试、单元测试和性能测试。

## 4. 总体架构

```text
需求 / 验收标准 / 手工用例 / 缺陷复现       前端源码 / 可访问运行时
                    |                              |
                    v                              v
        +-----------------------------+   +--------------------------+
        | Codex Control Plane         |   | Discovery Plane          |
        | Skills / Prompt / Policies  |<->| Source + Runtime + Net   |
        +--------------+--------------+   | Reconcile / Catalog/Gaps |
                       |                  +------------+-------------+
                       |                               |
                       +---------------+---------------+
                                       |
                                       v
        +-----------------------------+
        | Test Contract Plane         |
        | Test Card -> YAML / JSON IR |
        | Schema / Version / Review   |
        +---------+-------------+-----+
                  |             |
       Agentic    |             |    Deterministic
       Explore    |             |    Regression
                  v             v
        +----------------+  +------------------+
        | Playwright MCP |  | Playwright Runner|
        | Session/Tools  |  | Compile + Execute|
        +--------+-------+  +---------+--------+
                 \                   /
                  +--------+---------+
                           |
                           v
                +-------------------------+
                | Browser / Test Environment|
                | Web App + API + Test Data|
                +------------+------------+
                             |
                             v
                +-------------------------+
                | Evidence & Oracle Plane |
                | Trace / DOM / Network   |
                | Assertions / Report     |
                +------------+------------+
                             |
                             v
                +-------------------------+
                | Codex Failure Triage    |
                | Classify / Explain      |
                | Propose, never approve  |
                +-------------------------+
```

### 4.1 五个平面

| 平面 | 责任 | 核心产物 |
| --- | --- | --- |
| Control Plane | Codex 会话、Skill 选择、工具策略、输出 Schema | 执行计划、分析建议、结构化结果 |
| Contract Plane | 测试意图、数据引用、断言、风险等级、版本 | Test Card、Test Contract、审批记录 |
| Discovery Plane | 源码清点、运行时探索、证据对账和流程候选 | Source Graph、Runtime Graph、Reconciliation、Process Catalog、Coverage |
| Execution Plane | MCP 探索或确定性 Playwright 回归 | 步骤结果、浏览器会话、执行日志 |
| Evidence Plane | 取证、断言、报告、归档和审计 | Trace、截图、DOM、网络、控制台、报告 |

### 4.2 三种运行模式

| 模式 | 驱动方式 | 用途 | 是否有测试裁决权 |
| --- | --- | --- | --- |
| `explore` | Codex + Playwright MCP | 新功能探索、生成契约、定位建议 | 否，只能输出观察结果 |
| `verify` | Test Contract + Playwright Runner | 日常回归、发布门禁 | 是，由确定性断言裁决 |
| `assist` | Codex + 证据包 | 失败分类、缺陷摘要、修复建议 | 否，只能给出建议 |

这个区分是整套方案最重要的设计。没有它，系统会在“看起来通过”和“真正通过”之间失去边界。

### 4.3 系统流程发现与最佳定位

“最佳定位”不应只理解为单个元素选择器。可维护的 UI 自动化需要先建立系统级定位证据：

```text
前端源码 ----------> Source Graph（路由、页面入口、导航定义）
Playwright --------> Runtime Graph（角色、可达页面、跳转、控制台）
XHR / fetch -------> Network Evidence（接口依赖和行为线索）
        \               /
         Python Reconciler
               |
     流程候选目录 + 覆盖缺口
               |
     Test Card -> Contract -> Runner
```

- 前端源码回答“系统声明了哪些页面和入口”。
- Playwright 回答“当前环境、当前角色实际能到达哪些页面”。
- 网络证据回答“页面依赖哪些已观察接口”。
- Python 负责稳定 ID、图合并、去重、覆盖率、Schema 和产物落盘。
- AI 只做流程命名、语义归纳、风险解释和缺口建议，不生成权威测试结论。

覆盖率包括 `routeCoverage`、`transitionCoverage`、`roleCoverage` 和 `processCoverage`。它们衡量证据覆盖，不代表需求覆盖或业务正确率。路由 `matched` 只表示源码与运行时对账成功。

## 5. 测试资产模型

### 5.1 双层资产

建议保留两层资产：

1. **Test Card**：业务人员维护的自然语言测试意图。
2. **Test Contract**：可执行、可校验、可版本化的结构化用例。

Test Card 示例：

```yaml
id: LOGIN-001
title: 正确账号可以登录并进入首页
priority: P0
given:
  - 测试账号已存在且未锁定
  - 用户当前未登录
when:
  - 打开登录页
  - 输入正确用户名和密码
  - 点击登录
then:
  - 页面进入首页
  - 页面显示退出登录入口
  - 接口登录成功且业务状态正确
dataRefs:
  - TEST_USER
  - TEST_PASSWORD
```

### 5.2 Test Contract 示例

```yaml
schemaVersion: "1.0"
id: LOGIN-001
title: 正确账号可以登录并进入首页
priority: P0
platform: web
owner: qa-login
mode: verify

target:
  environment: staging
  baseUrlRef: WEB_BASE_URL
  allowedOrigins:
    - https://staging.example.com

preconditions:
  - type: account
    ref: login_user_001
    state: active

data:
  username:
    secretRef: TEST_USER
  password:
    secretRef: TEST_PASSWORD

steps:
  - id: open-login
    intent: 打开登录页
    action: navigate
    url: /login

  - id: fill-username
    intent: 输入用户名
    action: fill
    locator:
      testId: login-username
      role: textbox
      name: 用户名
    value: ${data.username}

  - id: fill-password
    intent: 输入密码
    action: fill
    locator:
      testId: login-password
      role: textbox
      name: 密码
    value: ${data.password}

  - id: click-login
    intent: 点击登录
    action: click
    locator:
      testId: login-submit
      role: button
      name: 登录

assertions:
  - id: entered-home
    type: url
    operator: matches
    expected: /home

  - id: logout-visible
    type: visible
    locator:
      role: button
      name: 退出登录

  - id: login-api
    type: network
    request:
      method: POST
      path: /api/login
    expected:
      status: 200

evidence:
  trace: always
  screenshot: on-failure
  accessibilitySnapshot: on-failure
  network: always
  console: always

risk:
  level: normal
  destructive: false
  financial: false
  approvalRequired: false
```

### 5.3 Contract 设计原则

- `intent` 是业务事实，`locator` 是执行提示，两者不能混为一谈。
- 首选 `testId`、`role + accessible name`，其次 label、text，CSS/XPath 只能作为受控兜底。
- 断言必须可重复、可解释、可定位证据。
- Secret 只保存引用，不写入 Contract、Prompt、截图文件名或日志。
- 测试数据必须声明创建、隔离和清理策略。
- 高风险动作必须声明审批策略。
- Contract 必须有 Schema 版本，模型、Skill 和工具版本必须进入运行记录。

## 6. Skill 设计

Skill 应该固化“可重复的工程判断”，而不是复制 Playwright 文档或写死某个页面。

### 6.1 推荐 Skill 清单

| Skill | 是否必需 | 作用 |
| --- | --- | --- |
| `ui-test-orchestrator` | 必需 | 通过 Playwright MCP 执行探索、调用工具、采集证据、输出观察结果 |
| `ui-test-authoring` | 必需 | 把需求、Test Card、手工用例转成 Test Contract |
| `ui-test-triage` | 必需 | 根据证据分类失败、生成缺陷摘要和定位修复建议 |
| `ui-source-inventory` | 流程发现必需 | 只读清点前端路由、页面入口、导航定义和源码证据 |
| `ui-system-explorer` | 流程发现必需 | 按角色隔离、只读探索运行时页面、跳转和网络证据 |
| `ui-process-cataloger` | 流程发现必需 | 合并源码与运行时证据，生成流程候选和覆盖缺口 |
| `playwright-browser-policy` | 可合并 | 定位优先级、等待策略、禁止动作、浏览器工具白名单 |
| `api-db-oracle` | 按需 | 通过 API/DB 验证业务状态，避免只看 UI |
| `visual-oracle` | 按需 | Canvas、图表、遮挡、白屏等视觉辅助判断 |

### 6.2 系统 Skill 的用途

| 系统 Skill | 在本方案中的用途 |
| --- | --- |
| `openai-docs` | 核对 Codex、MCP、Skills、`codex exec` 的官方能力与配置 |
| `skill-creator` | 创建、评审和校验自定义测试 Skill |
| `skill-installer` | 从可信仓库安装官方或内部 Skill |
| `imagegen` | 不用于本项目主链路，除非需要生成测试视觉素材 |

如果团队采用 Playwright CLI + Skills 做高频回归，可以评估官方 Playwright Skill；它更适合节省上下文和批量执行，MCP 更适合需要持续页面状态的探索流程。

### 6.3 Skill 组织方式

```text
.codex/
  skills/
    ui-test-orchestrator/
      SKILL.md
    ui-test-authoring/
      SKILL.md
    ui-test-triage/
      SKILL.md
    ui-source-inventory/
      SKILL.md
    ui-system-explorer/
      SKILL.md
    ui-process-cataloger/
      SKILL.md
```

本仓库已经提供上述六个中文 starter skill，可作为首轮 PoC 的基础；后续再增加 API/DB 和视觉 oracle。

中文团队的 Skill 命名约定：

- `name` 和目录名使用小写英文、数字和连字符，保证可被 Codex 稳定发现。
- `description`、正文、审核清单和输出说明使用中文。
- 工具名、字段名、状态值和命令保留英文，避免机器解析歧义。
- 业务术语建立中英文对照表，例如“测试契约 / Test Contract”，避免同义词漂移。

### 6.4 Skill 触发示例

生成测试契约：

```text
使用 $ui-test-authoring，把 tests/cards/LOGIN-001.yaml 转成 Test Contract。
页面地址由 staging 环境提供。缺少的信息标记 TODO，不要猜测接口或测试数据。
```

执行 MCP 探索：

```text
使用 $ui-test-orchestrator，在 staging 执行 LOGIN-001 的 explore 模式。
只允许访问 staging.example.com；不要执行删除、支付或权限变更操作。
输出 observed 结果、证据路径和未验证假设，不要宣称测试正式通过。
```

失败分析：

```text
使用 $ui-test-triage，分析 artifacts/runs/<run-id>。
区分产品缺陷、用例缺陷、定位漂移、环境问题和偶现。
只提出定位修复建议，不得修改业务断言。
```

## 7. Playwright MCP 接入

### 7.1 安装方式

开发机可以先使用 Codex CLI 注册 MCP Server：

```powershell
codex mcp add playwright -- npx -y "@playwright/mcp@<PINNED_VERSION>"
```

查看配置：

```powershell
codex mcp get playwright --json
```

如果使用 `$CODEX_HOME/config.toml`，可参考：

```toml
[mcp_servers.playwright]
command = "npx"
args = [
  "-y",
  "@playwright/mcp@0.0.84",
  "--headless",
  "--isolated",
  "--block-service-workers",
  "--redact-url-params",
  "access_token,code,state",
  "--output-dir",
  "./artifacts/playwright-mcp",
  "--allowed-origins",
  "https://staging.example.com"
]
```

注意：

- `0.0.84` 是本文核验时的版本基线；生产环境不要使用 `@latest`，应锁定团队验证过的版本并进入内部制品库。
- `--allowed-origins`/`--blocked-origins` 不是完整的安全边界；还必须在网络层限制出口。
- 如果启用 `--allow-unrestricted-file-access`，必须单独做安全评审。
- 企业内网可改用 `--executable-path` 指向经过安全校验的浏览器，避免依赖公共浏览器下载源。
- 仓库提供 `.codex/config.example.toml`，不会自动加载，也不会覆盖用户现有配置。
- 本机未改动全局配置；`scripts/run-mcp-smoke.ps1` 使用一次性配置完成注册、导航、快照、结构化输出和证据校验。
- 非交互 `codex exec` 调用 MCP 需显式使用 `--approve-for-me`，否则审批策略 `never` 会阻止工具调用。该参数只应作用于隔离测试环境。

可重复烟测：

```powershell
npm run test:mcp
```

### 7.2 浏览器工具策略

| 工具族 | 用途 | 默认策略 |
| --- | --- | --- |
| navigate | 打开页面 | 只允许契约声明或 allowlist 内的 URL |
| snapshot | 获取可访问性树 | 每次关键动作前后按需获取 |
| click/type/press | 执行用户动作 | 只执行 Contract 中的意图 |
| screenshot | 失败留证和视觉辅助 | 失败必存，敏感页面脱敏 |
| console/network | 诊断和断言 | 默认采集摘要，不保存敏感正文 |
| evaluate | 页内脚本 | 默认禁止；确有需要时走独立审批 |
| file upload/download | 文件流程 | 限制目录、类型和大小 |
| dialog | 弹窗处理 | 只在契约声明时接受 |

### 7.3 等待与重试

- 禁止把固定 `sleep` 作为默认等待方式。
- 使用 Playwright 的 actionability 等待和显式页面状态等待。
- 定位失败可以刷新快照后受控重试一次。
- 网络或环境波动可以有限重试，但必须记录。
- 业务断言失败不重试、不改写断言、不自动关闭缺陷。

## 8. 零代码使用体验

### 8.1 业务测试人员的入口

最小入口可以只是 Codex 对话：

```text
执行 tests/contracts/LOGIN-001.yaml，环境 staging，模式 verify。
失败时生成证据摘要，但不要自动修改用例。
```

随后可以包装成固定命令或内部平台按钮，但底层仍然是同一套 Skill 和 Contract：

```text
选择用例 -> 选择环境 -> 点击“执行” -> 查看结果和证据 -> 人工审核建议
```

确定性执行入口：

```powershell
$env:WEB_BASE_URL = "http://127.0.0.1:4173"
$env:DEMO_USER = "demo"
$env:DEMO_PASSWORD = "demo123"
py -X utf8 scripts\run_contract.py tests\contracts\LOGIN-001.yaml
```

浏览器缓存版本不匹配时，可以设置 `PLAYWRIGHT_EXECUTABLE_PATH`；该能力只用于锁定已审核浏览器，不会改变断言和裁决逻辑。

### 8.2 Codex 非交互入口

`codex exec` 适合内部平台或 CI 触发代理分析：

```powershell
codex exec `
  --ephemeral `
  --approve-for-me `
  --json `
  --output-schema ./schemas/codex-run-result.schema.json `
  --skip-git-repo-check `
  "使用 $ui-test-orchestrator 执行 tests/contracts/LOGIN-001.yaml，环境 staging，输出探索结果和证据清单。"
```

真实 MCP 调用还需要在隔离环境中注册 Server。仓库的 `npm run test:mcp` 已封装按需启动 Python 示例站、一次性注册、调用 Codex、用 Python 校验 Schema 和快照的完整链路。

注意：`--approve-for-me` 只解决非交互审批，不是安全授权边界。不要把“代理执行成功”直接当成发布门禁；发布门禁应由 `verify` 模式的确定性 Playwright 执行结果决定。

### 8.3 报告结构

建议每次运行输出统一 JSON：

```json
{
  "runId": "run-20261101-001",
  "caseId": "LOGIN-001",
  "mode": "explore",
  "observedStatus": "observed-pass",
  "authoritativeStatus": null,
  "startedAt": "2026-11-01T10:00:00+08:00",
  "endedAt": "2026-11-01T10:00:03+08:00",
  "steps": [
    {
      "id": "open-login",
      "intent": "打开登录页",
      "action": "browser_navigate",
      "status": "observed-pass",
      "locatorUsed": null,
      "durationMs": 820,
      "error": null
    }
  ],
  "assertions": [
    {
      "id": "login-button-visible",
      "type": "accessibility_snapshot_element_present",
      "status": "observed-pass",
      "actual": "button \"登录\" [ref=e10]",
      "durationMs": 0,
      "error": null
    }
  ],
  "evidence": {
    "trace": "artifacts/runs/run-20261101-001/trace.zip",
    "snapshot": "artifacts/playwright-mcp/page-20261101-100003.yml",
    "screenshot": "artifacts/runs/run-20261101-001/failure.png",
    "networkSummary": "artifacts/runs/run-20261101-001/network.json",
    "consoleSummary": "artifacts/runs/run-20261101-001/console.json"
  },
  "classification": {
    "category": "unknown",
    "confidence": 0.4,
    "reviewRequired": true,
    "summary": "仅完成探索观察，未产生权威测试结论。"
  },
  "assumptions": [
    "未调用确定性 Runner，因此不能作为发布门禁。"
  ],
  "versions": {
    "codex": "0.166.0-alpha.5.1",
    "playwrightMcp": "0.0.84",
    "skill": "ui-test-orchestrator@0.1.0"
  },
  "error": null
}
```

严格 Schema 下对象不能省略字段，不存在的可选证据写 `null`。`evidence.snapshot` 应引用 MCP 真实落盘文件，不能写 `inline-snapshot` 或虚构路径。工具失败时顶层 `error` 写 `{ "name": "...", "message": "...", "code": "..." }`，并将状态设为 `blocked`。

`observed-pass` 不等于 `passed`。状态语义必须写进报告和看板，否则很容易产生假通过。

## 9. 执行流程

### 9.1 预检

1. 校验 Contract Schema。
2. 校验环境、URL、账号和数据可用性。
3. 校验网络 allowlist、Secret 引用和操作风险。
4. 在页面稳定或基础健康检查失败时立即 `blocked`，不要盲目继续。
5. 创建独立浏览器上下文和运行目录。

### 9.2 执行

1. Codex 读取 Skill 和 Contract。
2. MCP 获取可访问性快照，确认页面与目标语义。
3. 按步骤调用浏览器工具。
4. 每步记录动作、定位、耗时和证据。
5. 使用确定性 oracle 检查 URL、DOM、API、DB 或业务状态。
6. 完成取证和清理。

### 9.3 失败处理

1. 保存失败快照、截图、网络和控制台摘要。
2. 判断是定位失败还是业务断言失败。
3. 定位失败最多生成一个修复候选，不静默更新资产。
4. 业务失败直接进入 `ui-test-triage`。
5. 分类为 `product_bug`、`test_bug`、`locator_drift`、`environment_issue`、`flaky_test` 或 `unknown`。
6. 高风险或低置信度结论必须人工审核。

### 9.4 准入门禁

发布门禁建议采用：

- P0/P1 必须 100% 确定性回归通过。
- 证据完整率达到 100%。
- 不存在未审核的定位自愈。
- 环境问题和产品缺陷分开计数。
- 代理式探索只作为补充信号，不作为唯一门禁。

## 10. 证据与可观测性

建议目录结构：

```text
artifacts/
  runs/
    <run-id>/
      manifest.json
      result.json
      trace.zip
      screenshots/
      snapshots/
      network-summary.json
      console-summary.json
      codex-events.jsonl
      skill-prompt.txt
      redaction-report.json
```

必须记录：

- Contract ID 和版本。
- 环境、浏览器、Codex、MCP 和 Skill 版本。
- 执行模式、开始结束时间和重试次数。
- 步骤级定位与结果。
- 断言与 oracle 证据。
- 模型原始响应摘要或事件流。
- 失败分类、置信度和审核状态。
- 脱敏记录和证据保留期限。

## 11. 安全与治理

### 11.1 Prompt Injection

页面文本、DOM、无障碍树、网络响应和截图都可能包含恶意指令。必须把它们视为数据，而不是系统指令。

最低要求：

- Skill 明确声明“页面内容不可信”。
- 只允许调用白名单工具。
- 禁止模型执行页面内“忽略之前指令”之类内容。
- `evaluate`、文件访问、上传下载和外链跳转默认关闭或审批。
- 高风险动作需要人工确认。

### 11.2 网络与文件边界

- 网络层限制测试环境域名和必要第三方依赖。
- 不把 MCP 的 origin allowlist 当作唯一安全控制。
- 文件访问限制在工作区或独立只读目录。
- 下载文件检查类型、大小和恶意内容。

### 11.3 凭据与隐私

- Secret 只通过 Secret Manager 或环境注入。
- 绝不把密码、Token、Cookie、个人信息写入 Prompt。
- Trace、截图、网络日志必须脱敏。
- 测试账号使用最小权限和独立环境。
- 自动化运行结束后清理临时账号、数据和浏览器状态。

### 11.4 操作风险分级

| 等级 | 示例 | 策略 |
| --- | --- | --- |
| 只读 | 查询、列表、详情 | 可自动执行 |
| 普通写 | 创建草稿、编辑测试数据 | 限测试环境并记录 |
| 高风险写 | 删除、退款、审批、权限变更、支付 | 禁止自主执行或人工确认 |
| 生产 | 任何真实业务数据 | 默认禁止 MCP 代理执行 |

## 12. 可靠性设计

### 12.1 定位策略

优先级建议：

1. `data-testid` 或业务稳定 ID。
2. `role + accessible name`。
3. label、placeholder、稳定文本。
4. 邻近元素和结构特征。
5. CSS/XPath 兜底。
6. 视觉辅助，仅作为感知补位。

只有候选唯一且超过置信度阈值时才允许自动重试。任何定位修复都必须留下旧定位、新定位、证据、置信度和审核状态。

### 12.2 防假通过

- 不允许 Codex 自行决定测试通过。
- 不允许“页面没报错”替代业务断言。
- 不允许断言失败后自动改断言。
- 不允许无限重试直到通过。
- 必须区分 `observed-pass`、`passed`、`blocked` 和 `review-required`。
- 关键业务结果优先使用 API/DB 或明确业务状态验证。

### 12.3 防 Flaky

- 独立浏览器上下文和测试数据。
- 自动等待，不使用固定 sleep。
- 网络、环境、定位和业务失败分开统计。
- 重试只用于已知环境波动，并记录重试链。
- 连续失败和间歇失败分开处理。

## 13. 指标与验收

### 13.1 质量指标

- 真实缺陷发现率。
- 假通过率，必须接近 0。
- 假失败率。
- Flaky 比例。
- 定位修复正确率。
- 失败分类准确率。
- 证据完整率。
- 人工审核驳回率。

### 13.2 效率指标

- 单条用例首次创建耗时。
- 页面改版后的修复耗时。
- 失败定位平均耗时。
- 单次运行 token 成本。
- MCP 会话时长和工具失败率。
- 人工审核占比。

### 13.3 PoC 建议验收线

首轮 PoC 选择 10 到 20 条 P0/P1 Web 用例：

- 连续三轮确定性回归稳定。
- 关键业务断言均有 API/DOM/URL 等确定性证据。
- 假通过为 0。
- 证据完整率达到 100%。
- 测试人员不修改 Playwright 脚本即可完成契约生成和调整。
- 失败分类在人工复核样本中达到可接受准确率，并记录误判。
- 高风险动作全部进入审批或禁止列表。
- 源码路由、运行时页面、角色、跳转和流程覆盖率能够输出证据化缺口，而不是宣称“已发现全部流程”。

## 14. 分阶段落地

### 阶段 0：边界和基线

- 选一个 Web 测试环境和 10 到 20 条 P0/P1 用例。
- 确定测试账号、数据创建/清理、登录态和网络策略。
- 固定 Codex、MCP、浏览器和 Skill 版本。
- 建立结果状态语义和证据目录。

### 阶段 1：只读探索与流程发现

- 安装并隔离 Playwright MCP。
- 建立 `ui-test-orchestrator`、`ui-source-inventory`、`ui-system-explorer` 和 `ui-process-cataloger`。
- 建立 Source Graph、Runtime Graph、Reconciliation 和 Process Catalog。
- 实现自然语言探索、观察结果、流程候选、覆盖缺口和证据包。
- 页面导航限制在 origin allowlist；非只读请求在路由层中止并记录。
- 不接发布门禁。

### 阶段 2：契约化

- 建立 Test Card 和 Test Contract Schema。
- 建立 `ui-test-authoring`。
- 测试人员通过自然语言生成和审核契约。
- 建立 Contract 版本和人工审批。

### 阶段 3：确定性回归

- 实现 Contract -> Playwright Runner。
- 接入 CI、报告、缺陷系统和证据归档。
- 将确定性回归设为发布门禁。

### 阶段 4：受控自愈与失败分析

- 接入 `ui-test-triage`。
- 只允许定位修复建议，不允许改业务断言。
- 增加候选评分、证据、审核和回滚。
- 在指标达标后才考虑更自主的探索。

## 15. 常见遗漏

以下问题最容易在方案评审时被忽略：

1. **测试预言没有定义**：知道怎么点按钮，不等于知道什么结果算正确。
2. **测试数据不可重复**：账号、库存、订单、时间、并发和清理策略。
3. **登录态和 MFA**：SSO、短信、OTP、验证码、Cookie 加密和过期。
4. **环境漂移**：服务版本、特性开关、灰度、第三方依赖和数据库快照。
5. **MCP 不是安全边界**：origin allowlist 不能替代网络出口控制。
6. **页面内容可注入**：无障碍树和截图也可能携带恶意指令。
7. **代理执行不可重复**：模型、Prompt、Skill 和工具版本变化会影响行为。
8. **证据成本**：Trace、视频、截图和模型的存储、保留和脱敏。
9. **模型成本**：高频回归全部走 Codex 可能成本过高，应优先确定性执行。
10. **定位不能只看 CSS**：组件库升级会大面积破坏 CSS/XPath。
11. **Canvas/iframe/shadow DOM**：可访问性树可能不完整，需要单独验证。
12. **视觉模型误判**：视觉相似不等于业务正确。
13. **自愈假通过**：修复定位后可能点错元素，业务断言仍必须独立验证。
14. **人工审核瓶颈**：需要定义哪些变更必须审核，避免流程变成人工排队。
15. **移动端不是同一方案**：Playwright MCP 不能直接替代 Appium 原生自动化。
16. **供应链风险**：MCP Server、浏览器、Node、模型和 Skill 都需要版本锁定。
17. **CI 凭据**：Codex 非交互运行需要认证、额度、代理和超时治理。
18. **审计要求**：谁改了用例、谁批准自愈、谁关闭缺陷。
19. **指标误导**：只看通过率会鼓励假通过，必须同时看漏报和误报。
20. **过度自动化**：探索式测试、可访问性、性能和接口契约应使用各自合适的工具。

## 16. 风险清单

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| Codex 把观察当结论 | 假通过 | 只有确定性 runner 有 `passed` 权限 |
| MCP 会话不可复现 | CI 不稳定 | 固定 Contract、Skill、MCP 和浏览器版本 |
| 页面注入攻击 | 数据泄露或越权操作 | 不可信内容、工具白名单、网络隔离、审批 |
| 测试数据污染 | 偶发失败 | 隔离账号、数据命名空间、清理任务 |
| 定位漂移 | 维护成本 | testId/role 优先，候选评分和人工审核 |
| 模型升级 | 行为漂移 | 固定评估集、回归评测和灰度升级 |
| 证据过多 | 存储和隐私风险 | 分层采集、脱敏、保留期限 |
| 成本过高 | 无法规模化 | 只让 Codex 做高价值环节，回归走确定性执行 |
| Skill 过宽 | 意外操作 | 小而专的 Skill、明确输入输出和停止条件 |
| 浏览器限制 | 覆盖不足 | 对 Canvas、iframe、移动端单独设计 |
| 把发现当测试通过 | 假通过 | 路由 `matched` 仅表示对账成功；业务结论必须由 Test Contract Runner 产生 |
| 把覆盖率当需求覆盖 | 过度乐观 | 同时报告 source-only、runtime-only、blocked 和未验证假设 |

## 17. 推荐目录

```text
ai-ui-test/
  .codex/
    skills/
      ui-test-orchestrator/
        SKILL.md
      ui-test-authoring/
        SKILL.md
      ui-test-triage/
        SKILL.md
      ui-source-inventory/
        SKILL.md
      ui-system-explorer/
        SKILL.md
      ui-process-cataloger/
        SKILL.md
  tests/
    cards/
    contracts/
  schemas/
    test-contract.schema.json
    run-result.schema.json
    codex-run-result.schema.json
    source-graph.schema.json
    runtime-graph.schema.json
    reconciliation.schema.json
    process-catalog.schema.json
    coverage.schema.json
    discovery-config.schema.json
    discovery-manifest.schema.json
  src/
    ui_test_poc/
      __init__.py
      contract.py
      schema.py
      runner.py
      cli.py
      discovery/
        source_index.py
        runtime_index.py
        reconcile.py
        catalog.py
        coverage.py
        config.py
        models.py
        schema.py
  scripts/
    run_contract.py
    run_demo.py
    run_failure_demo.py
    validate_codex_result.py
    verify_skills.py
  artifacts/
    runs/
  examples/
    login_app/
      server.py
    discovery_frontend/
      src/
        router.tsx
  discovery.example.yaml
  discovery.local.example.yaml
```

## 18. 最终建议

建议按以下决策落地：

1. **Web 优先**：首个 PoC 只覆盖 Web P0/P1 主链路。
2. **MCP 做探索和取证**：用于测试资产生成、页面理解、失败分析和受控重试。
3. **确定性执行做门禁**：Test Contract 由 Playwright Runner 回放，Codex 不拥有最终裁决权。
4. **先发现系统地图，再做用例**：用源码、运行时和网络证据建立路由与流程候选，显式记录覆盖缺口。
5. **自然语言是入口，YAML 是资产**：测试人员零代码，但资产必须结构化、可版本化。
6. **Skill 必须小而专**：编排、生成、取证、分类、源码清点、系统探索和流程对账分开，避免一个万能 Skill 携带过多权限。
7. **先人工审核，后受控自愈**：定位修复只生成建议，业务断言永远需要人工批准。
8. **安全与评测先行**：Prompt Injection、Secret、网络出口和假通过率要在 PoC 阶段验证，不要留到规模化后。

如果只能做一个最小版本，建议先实现：

```text
Test Card
  -> Codex 生成 Contract
  -> Playwright MCP 执行一次探索
  -> 采集证据
  -> 人工审核
  -> 确定性 Playwright 回放
  -> 输出统一报告
```

这条链路能同时证明“零代码可用”和“测试结果可信”，比直接追求全自主 Agent 更有工程价值。
