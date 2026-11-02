---
name: ui-process-cataloger
description: 合并前端源码、只读运行时和网络证据，生成可追溯的业务流程候选目录与覆盖缺口；不得宣称流程完整或测试通过。
metadata:
  short-description: 对账多源证据并生成流程目录
---

# 业务流程目录编制

当用户已有 Source Graph、Runtime Graph，或需要根据前端仓和运行环境总结全部可验证业务流程时，使用本 Skill。核心是对账证据和暴露缺口，不是生成看似完整的流程清单。

## 输入

- `source-graph.json`。
- `runtime-graph.json`。
- 角色、允许 origin、页面预算和运行时间窗口。
- 可选的 API 文档、权限矩阵和已有 Test Card。

缺失某一类证据时仍可产出候选目录，但必须降低置信度并列出缺口。

## 合并原则

- 源码负责发现定义：路由、组件、导航语句和入口。
- 运行时负责验证可达：页面、跳转、角色可见性和 HTTP 状态。
- 网络负责补充行为：只记录已观察的 XHR/fetch 及其分类。
- Python 负责图合并、去重、稳定 ID、覆盖率和产出文件。
- AI 只做语义归纳、命名和风险提示；不得覆盖原始证据或凭空补充步骤。

## 对账状态

- `matched`：源码声明存在且运行时至少到达一次，只代表路由可达。
- `source-only`：源码声明存在但本轮未到达，常见原因是权限、数据、入口或解析遗漏。
- `runtime-only`：运行时存在但源码索引未覆盖，可能是动态路由、第三方页面或源码遗漏。
- `conflict`：同一路径组件冲突，或源码存在但运行时返回 HTTP 错误。
- `blocked`：origin、凭据或访问限制导致无法继续。

禁止把上述状态转换为权威测试结论。

## 工作流程

1. 校验输入证据的 Schema、runId、时间窗口和角色范围。
2. 对账源码与运行时路径，匹配动态路由时使用模板而不是具体 ID。
3. 基于已观察跳转构造有界流程候选；不要枚举无限状态空间。
4. 将 API 依赖关联到页面和角色，仅使用已脱敏的请求摘要。
5. 为流程标注风险：支付、退款、权限、审批和删除类流程必须标记人工审批。
6. 生成 `reconciliation.json`、`process-catalog.json`、`processes/*.yaml` 和 `coverage.json`。
7. 检查四类覆盖率及缺口：路由、跳转、角色、流程步骤。

命令行示例：

```powershell
py -X utf8 -m ui_test_poc.cli discover reconcile `
  --source <source-dir> --runtime <runtime-dir> --output <evidence-dir>
py -X utf8 -m ui_test_poc.cli discover catalog `
  --reconciliation <evidence-dir> --output <evidence-dir>
py -X utf8 -m ui_test_poc.cli discover coverage `
  --reconciliation <evidence-dir> --catalog <evidence-dir> --output <evidence-dir>
```

也可以使用 `discover all --config discovery.yaml` 串联全流程。

## 输出要求

- 状态只能是 `review-required` 或 `complete`；默认使用 `review-required`。
- 每个流程必须引用源码、运行页面或网络证据，并给出置信度。
- 单独列出 `source-only`、`runtime-only`、`conflict`、`blocked`、页面预算耗尽和角色未覆盖。
- 明确说明覆盖率衡量的是证据覆盖，不是需求覆盖率、业务正确率或发布结论。
- 流程目录不能替代 Test Card；高风险分支和异常分支仍需人工补充验收标准。

中文调用示例：

```text
使用 $ui-process-cataloger，对账 source 和 runtime 证据，输出候选流程和缺口。
只根据证据命名流程；不要宣称“全部流程已发现”，也不要把路由 matched 说成测试通过。
```
