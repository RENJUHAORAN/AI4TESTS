---
name: ui-test-triage
description: 基于 UI 测试证据分类失败、总结缺陷并提出定位修复建议；不得修改业务断言或权威测试结论。
metadata:
  short-description: 根据证据分析 UI 测试失败
---

# UI 测试失败分析

当 UI 测试失败或结果不明确，用户要求根因分析、失败分类、偶现诊断、缺陷摘要或定位修复建议时，使用本 Skill。

## 必需证据

只读取运行目录中实际存在的证据。可用输入包括：

- 步骤结果和原始定位。
- 可访问性快照。
- 截图。
- 控制台和网络摘要。
- Trace 或视频。
- Contract 和测试数据版本。
- 上次成功运行记录。

证据不足时输出 `unknown` 并说明缺失内容。不得只凭一张截图推断产品缺陷。

## 分类

只能选择一个主分类：

- `product_bug`：产品或接口状态与预期业务结果矛盾。
- `test_bug`：契约、数据、oracle 或前置设置错误。
- `locator_drift`：同一语义元素仍存在，但旧定位失效。
- `environment_issue`：服务、网络、浏览器、设备、特性开关或测试数据基础设施异常。
- `flaky_test`：有证据表明设置或时序存在非确定性。
- `unknown`：证据不足或相互矛盾。

## 边界

- 不得修改权威测试结论。
- 不得为了让失败消失而改写业务断言。
- 没有具体业务矛盾证据时，不得声称是 `product_bug`。
- 定位修复只是建议，不是已批准的资产变更。
- 新定位必须有唯一性和稳定语义匹配证据。
- 低置信度、安全敏感、财务或破坏性操作必须升级给人工审核。

## 输出

返回：

1. 分类和置信度。
2. 一段有证据支撑的摘要。
3. 最强支持证据和矛盾证据。
4. 缺失证据。
5. 建议的下一步操作。
6. 如支持 `locator_drift`，给出旧定位、建议定位、理由和风险。
7. 低置信度或高风险时设置 `reviewRequired: true`。

示例：

```json
{
  "category": "locator_drift",
  "confidence": 0.92,
  "summary": "登录按钮的角色和可访问名称未变，但 testId 发生了变化。",
  "evidence": [
    "快照中存在 role=button、name=登录",
    "旧 testId login-submit 已不存在"
  ],
  "contradictoryEvidence": [],
  "missingEvidence": [],
  "suggestedAction": "建议审核 role=button[name='登录']，不得自动提交。",
  "reviewRequired": true
}
```
