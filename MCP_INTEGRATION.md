# MCP_INTEGRATION — 麦当劳 MCP 集成说明

## 使用的 MCP Server

| 项目 | 值 |
|---|---|
| 服务名称 | 麦当劳中国 MCP Server（官方远程托管） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 认证方式 | `Authorization: Bearer <MCP Token>`（Token 于 open.mcd.cn 申请） |

## 实际使用的 Tool 及用途

| Tool | 在本项目中的用途 | 状态 |
|---|---|---|
| `order-list` | 建档：拉取近期历史订单，从 `orderProductList[].comboItemList` 读取套餐子项实选，作为口味偏好的候选来源 | 已实机调用 |
| `query-meal-detail` | 核心：① 拉商品默认搭配，与实选做差集得到候选偏好；② 套用时校验定制项在当前菜单是否可用；③ 现取 `selectedKey` / `unselectedKey`（禁止硬编码） | 已实机调用（多轮） |
| `calculate-price` | 验证：对编译出的 `modification` / `roundList` payload 实测算价，确认定制生效、差价正确 | 已实机调用 |
| `create-order` | 下单：携带套用偏好后的商品列表创建订单 | 未下实单（算价端已验证 payload 合法） |
| `query-nearby-stores` / `delivery-query-stores` | 选店：确定订单的门店上下文 | 设计流程中依赖，未单独实机验证 |
| `now-time-info` | 获取当前时间，用于区分早餐/正餐菜单时段 | 设计流程中依赖，未单独实机验证 |

## 调用流程

```
第一幕 · 建档
  order-list（历史订单）
      └─> query-meal-detail（默认搭配）
              └─> 差集 = 候选偏好 ─> 用户确认 ─> 本地口味库

第二幕 · 套用（下单流程中自动，在 calculate-price 之前）
  1. 匹配：商品 code/名称 ─> 口味库候选规则
  2. 校验：query-meal-detail 确认定制项仍可用
  3. 构建：scripts/build_modification.py 生成 modification / roundList payload
     （同时输出 degraded 降级项与 conflicts 冲突项，冲突时交用户定夺）
  4. 告知：一句话说明应用了什么，留撤销入口

第三幕 · 防误存（下单后）
  临时改动只记 tempOverrides，单独确认后才升级为永久规则
```

## 关键工程结论（均来自实机验证）

这些是文档未明说、通过真实调用总结出的 MCP 行为，已固化为本项目的脚本逻辑：

1. **含 `unselectedKey` 的特调组（配料类）必须全量提交**——组内每一项都要传（选中 `selectedKey`，未选 `unselectedKey`），只传单项会被服务端判为组内其余未选。
2. **不含 `unselectedKey` 的组（冰量、甜度）是单选口味值**，只传选中项；「少冰」是 `set_option` 选值而非 `remove`。
3. **`selectedKey` / `unselectedKey` 必须每次从 `query-meal-detail` 现取**，非通用编码，不可跨商品复用。
4. **套餐子项 code ≠ 单品 code**（同一饮料在单点/中杯套餐/大杯套餐中是三个 code），口味库存语义、运行时匹配 code。
5. **套餐子项特调存在非必现的 `root: must be object` 客户端校验报错**（同一结构复测多次成功），据此设计了只重试一次 + 换子项 + 降级告知的容错策略。

详见 `references/mcp-customization.md`（实测样例，门店号已脱敏）与 `tests/fixtures/`（真实返回裁剪版）。

## 业务价值

麦当劳 MCP 提供了完整的点餐、算价、下单能力，但没有「用户偏好存储」——用户每次点单都要重复报一遍定制要求，且定制参数的构造规则复杂、易错（全量提交、key 现取、code 区分）。本项目在这层缺口上补齐：

- **对用户**：偏好一次建档，之后每单自动套用，省去重复沟通；选项失效自动降级并明确告知，不会悄悄改单。
- **对麦当劳 MCP 生态**：展示了「MCP 出点餐能力、Skill 出记忆与个性化」的分层范式；把定制参数的正确构造封装成脚本，降低其他开发者在 modification / roundList 上踩坑的成本。
- **对下单质量**：编译式生成 payload + 20 条离线回归，把「模型临场拼参数」的不确定性变成可测试的确定性。
