---
name: ui-test-authoring
description: 将需求或验收标准先整理为中文 Test Card，再转换为可审核的结构化 Web UI Test Contract，明确测试数据、确定性断言、证据和风险。
metadata:
  short-description: 编写 Test Card 和 UI Test Contract
---

# UI 测试编写

当用户要求创建或修改 Web UI 测试卡、测试契约、验收用例、回归用例或测试数据矩阵时，使用本 Skill。

## 目标

同时生成一份业务可读的 Test Card 和一份可校验、可由确定性执行器回放的 Test Contract。业务测试人员不需要编写 Playwright 代码。

除非用户明确说明只需要 Contract 草稿，否则不得只输出 Contract。默认交付必须包含：

- `tests/cards/<CASE_ID>.yaml`：业务意图、前置条件、动作、预期结果和安全约束。
- `tests/contracts/<CASE_ID>.yaml`：可执行步骤、定位器、确定性断言、证据和风险。

两份文件必须使用相同的大写用例 ID，并表达同一业务结果。业务意图不明确时先输出 Card 和待确认问题，不得直接发明可执行断言。

## 编写规则

- 忠实保留业务意图，不得发明需求、接口、选择器、账号或期望值。
- 未知信息标记为 `TODO`，并列入待确认问题。
- 明确区分业务 `intent` 和定位提示 `locator`。
- 一个用例聚焦一个清晰业务结果；只有验收标准需要时才增加反向或边界场景。
- Secret 只使用 `secretRef` 引用，禁止内联凭据。
- 优先使用 `testId` 和 `role + accessible name`；稳定用户可见文本只能作为后备。
- 每个业务结果必须有明确 oracle，不能把“页面没有报错”作为断言。
- 声明环境、允许的 origin、风险、证据和清理要求。
- 未单独授权时，不执行测试。

## 编写流程

1. 提取参与者、前置条件、业务数据、动作、预期结果和清理要求。
2. 找出不可观察、含糊或缺少验收标准的业务点。
3. 按需要建立正向、反向、权限、边界和并发场景矩阵。
4. 先按 `tests/cards/` 的现有格式编写中文 Test Card。
5. 读取同 ID Card，按仓库中的 Test Contract Schema 编写可执行 Contract。
6. 检查 Card 中的每个业务预期都能在 Contract 中找到确定性 oracle。
7. 断言优先顺序为：业务/API/DB 状态、网络结果、URL、可访问 UI 状态、视觉比较。
8. 对高风险或破坏性动作标记审批要求。
9. 返回两个资产路径、差异说明和简短审核清单。

## 最小 Test Card 结构

```yaml
id: TODO
title: TODO
priority: P1
given:
  - TODO
when:
  - TODO
then:
  - TODO
dataRefs:
  - TODO
constraints:
  - TODO
```

## 最小契约结构

```yaml
schemaVersion: "1.0"
id: TODO
title: TODO
priority: P0
platform: web
owner: TODO
mode: verify
target:
  environment: TODO
  baseUrlRef: TODO
  allowedOrigins: []
preconditions: []
data: {}
steps: []
assertions: []
evidence:
  trace: always
  screenshot: on-failure
  network: always
  console: always
risk:
  level: normal
  destructive: false
  approvalRequired: false
```

## 审核清单

- Test Card 与 Test Contract 已按同一用例 ID 成对创建。
- Card 使用中文表达业务意图，Contract 不新增 Card 中不存在的业务结论。
- Card 中的每个业务预期都有对应的确定性断言。
- 预期业务状态没有歧义。
- 每个动作都有业务意图和目标。
- 每个业务断言都有确定性 oracle。
- Secret 和测试数据清理策略已定义。
- 用例可以隔离执行并安全重试。
- 未知项已显式标记，而不是被猜测填补。
