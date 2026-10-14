# WorkBuddy 使用记录（mcd-taste-memory）

本项目于 2026-10-13 使用腾讯 WorkBuddy 完成开发，本文为真实使用过程记录。

## 项目背景

每次点麦当劳都要重复说「不要酸黄瓜、可乐换雪碧」。麦当劳 MCP 提供了完整的点餐能力，但不提供「偏好存储」——于是用 WorkBuddy 开发了这个口味记忆层 Skill：本地 JSON 口味库 + 偏好编译脚本，让每一单都比上一单省一句话。

## 开发过程（按实际时间线整理）

### 第一步：接入麦当劳 MCP

- 在 open.mcd.cn 申请 MCP Token，在 WorkBuddy 中配置 `mcd-mcp`（Streamable HTTP）。
- 在 WorkBuddy 对话中逐个试用 MCP 工具，确认可调用：`query-meals`、`query-meal-detail`、`calculate-price`、`order-list`、`query-nearby-stores` 等。

### 第二步：实机摸清定制参数的真实结构

这是本项目工作量最大、也是 WorkBuddy 帮助最大的环节。通过 WorkBuddy 对话驱动真实 MCP 调用（到店自提场景，门店号已脱敏），逐项验证并沉淀进 `references/mcp-customization.md`：

- **全量提交规则**：含 `unselectedKey` 的特调组（配料类）必须组内全量提交，只传一项「不要酸黄瓜」会导致服务端把其余配料判为未选。
- **单选口味值**：不含 `unselectedKey` 的组（冰量、甜度）是 N 选 1，只传选中项；「少冰」是 `set_option` 选值，不是 `remove`。
- **key 现取**：`selectedKey` / `unselectedKey` 不是通用编码，每次必须从 `query-meal-detail` 现取，禁止硬编码。
- **套餐子项 code ≠ 单品 code**：同一款雪碧在单点和套餐中是三个不同 code。
- **非必现报错**：套餐子项特调偶发 `root: must be object` 客户端校验报错，经 2026-10-13 16:57 同结构逐字复测返回 200，确认属间歇性问题，据此设计了「只重试一次 + 换子项 + 降级告知」的降级矩阵。

### 第三步：脚本与测试

在 WorkBuddy 中完成两个核心脚本：

- `scripts/taste_store.py` — 口味库读写（纯本地 JSON，软删除保留历史）
- `scripts/build_modification.py` — 把口味库偏好编译为可直接塞进 `items[]` 的 `modification` / `roundList` 参数，并输出 `applied` / `degraded` / `conflicts` 三条说明

配套 `tests/test_offline.py` 共 20 条离线回归用例，覆盖「错了就会下错单」的硬性规则（全量提交、套餐换子项、降级、冲突不猜、临时改动不自动升级等），**20/20 通过**。离线运行：不联网、不调 MCP、不碰真实口味库。

### 第四步：算价端验证

用 `calculate-price` 对编译出的 payload 实测算价：定制项生效、差价正确。`create-order` 端点未下过实单，已在 README 中如实标注。

## WorkBuddy 的价值

1. **探索未知 API 结构**：MCP 文档不会告诉你特调组的全量提交规则和 key 现取要求，这些都是在 WorkBuddy 对话中实机调用、对照返回结构总结出来的，并直接固化成了脚本逻辑和测试用例。
2. **把踩坑变成资产**：每次踩坑（如 `root: must be object`）都在 WorkBuddy 中分析根因、写入 references 和降级矩阵，避免重复踩。
3. **工程化产出**：从创意到可安装、可回归测试的 Skill 包，全部在 WorkBuddy 工作区内完成，并直接推送到 GitHub 参赛仓库。

## 数据可核实性

本文所述过程均有实物佐证：`references/mcp-customization.md`（2026-10-13 实机调用记录，门店号脱敏）、`tests/fixtures/`（同一次抓取的真实 `query-meal-detail` 返回，已裁剪）、`tests/test_offline.py`（20 条用例可独立复跑）。
