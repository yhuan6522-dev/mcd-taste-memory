---
name: mcd-taste-memory
description: 麦当劳点餐的「口味记忆层」——记住你的定制偏好（不要酸黄瓜、可乐换雪碧、咖啡少冰），下单时自动套用，选项失效时降级为默认并明确告知。当用户要点麦当劳、查麦当劳菜单、算价、下单、创建订单时使用；也用于首次从历史订单建档、查看或修改口味偏好、把某次临时改动固化为长期习惯。非口令触发，随点餐流程自动生效。
---

# 麦麦口味记忆

通用点餐之上的记忆层。点餐本身照常走麦当劳 MCP，本 Skill 只负责一件事：**让每一单都比上一单更省一句话**。

## 三幕闭环

### 第一幕 · 建档（口味库不存在时）

1. 调 `order-list` 拉近期历史订单，从 `orderProductList[].comboItemList` 读套餐子项实选 code。
2. 用 `query-meal-detail` 拉出这些商品的默认搭配，与实选做差集——差异即候选偏好。
3. 逐条向用户确认后写入。**写入前必须让用户过一次目，绝不静默入库。**

> 已核实边界：`order-list` 的响应结构只声明到 `comboItemList`，**未声明特调（modification）字段**。
> 因此：套餐子项替换（可乐→雪碧）可稳定回溯；单品特调（去酸黄瓜）在无历史特调数据时**无法回溯**。
> 此时走冷启动降级：用 `query-meal-detail` 拉常点单品的特调项，逐项问一次（见下方降级矩阵）。

### 第二幕 · 套用（下单流程中自动）

在 `calculate-price` 之前插入四步：

1. **匹配** — 用当前商品 code / 名称查口味库，命中得候选规则集。
2. **校验** — 用 `query-meal-detail` 确认这些定制项在当前门店当前菜单里仍然可用。
3. **构建** — 用 `scripts/build_modification.py` 生成 `modification` payload，不手拼。
   脚本同时输出 `degraded`（哪条没生效、为什么）和 `conflicts`（哪几条互相打架）。
   **有 conflicts 时不要套用那一项**，把两条摆给用户选，别自己挑一个。
4. **告知** — 一句话说明应用了什么，并留撤销入口：

> 检测到 3 条偏好，已为你应用：不要酸黄瓜、可乐换雪碧、咖啡少冰。
> 回复「撤销第 2 条」可单独取消，回复「全部撤销」用默认搭配。

套用结果落 `lastApplied`，供第三幕比对。

### 第三幕 · 防误存（下单后）

套用后用户若临时改动（比如这次又加了酸黄瓜），**只记入 `tempOverrides`，绝不自动升级为永久偏好**。
单独问一次：

> 这次你把酸黄瓜加回来了。是一次性的，还是以后都加？（回复「以后都加」我更新口味库）

确认后才 `promote` 进 `rules`。

## 硬性规则

违反任何一条都会下出错的单：

1. **同组全量提交**。含 `unselectedKey` 的特调组，组内每一项都必须传入：选中项用 `selectedKey`，未选中项用 `unselectedKey`。只传一个「酸黄瓜」是错的。
2. **两类特调组别混写**。
   - 含 `unselectedKey` = **配料**（酸黄瓜、洋葱粒、糖、奶油球）→ 可增减，按第 1 条全量提交。
   - 不含 `unselectedKey` = **单选口味值**（冰量、甜度）→ N 选 1，**只传选中那一项**，多传等于同时点两个口味值。
   - 所以「少冰」「去冰」是 `set_option` **选值**，不是 `remove` 掉冰。写成 remove 会被降级（脚本会提示改法）。
3. **key 实时取**。`selectedKey` / `unselectedKey` 每次从 `query-meal-detail` 现取，禁止硬编码、禁止跨商品复用。
4. **套餐子项 code ≠ 单品 code**。雪碧：单品 `3010`，套餐中杯 `3060`，大杯 `3110`。口味库存**语义**（round 名 + 选项名），运行时再匹配 code。
5. **不可用必降级**。校验不通过的规则静默丢弃并明确告知，剩下的照常下单。
6. **不命中就不改**。某商品无规则命中时不要生成 `modification`，保持默认。
7. **临时改动不自动升级**。见第三幕。

## 降级矩阵

| 场景 | 处理 |
|---|---|
| 商品下架 / code 失效 | 规则标记 `stale`，提示「XX 已不在菜单，该偏好已跳过」 |
| 特调项不在当前菜单 | 该项降级为默认，明确告知哪一条没生效 |
| `supportModify=true` 但 `values` 为空 | 视为不可定制，降级为默认 |
| 历史订单无特调数据 | 转冷启动问卷：拉常点单品特调项逐项问 |
| 规则互相冲突（同组又去又要） | 该项保持默认，把两条摆给用户选，不自动挑 |
| 套餐子项特调报 `root: must be object` | 非必现（同一结构多次成功）。只重试一次，仍失败按下面三段式降级 |

### 子项特调报 root: must be object 时

这是**间歇性**的客户端校验报错，不是 payload 错——同一结构实测多次成功（见 `references/mcp-customization.md` 第三节）。所以不要一上来就放弃子项特调。

1. **照常提交**，失败后**只重试一次**，仍失败就停手，不要改结构硬凑。
2. **换子项照做**（换饮料、换小食走 `roundList`，通道一直可用）。
3. 给用户两条路，附算价结果：接受默认配料；或拆成单点（单品级特调可用）但失去套餐价。**让他自己选。**

## 自测

改完脚本先跑回归，20 条用例覆盖「错了就会下错单」的那几条（全量提交、套餐换子项、降级、必选项、冲突不猜、临时改动不升级）：

```bash
python3 tests/test_offline.py -v
```

离线跑，不联网、不调 MCP、不动真实口味库（每个用例用临时目录）。

## 口味库

默认路径 `~/.workbuddy/mcd-taste-memory/taste.json`（本地 JSON，MCP 无偏好存储接口；后续可迁账号云端）。
结构、字段与匹配算法见 `references/taste-schema.md`。

```bash
python3 scripts/taste_store.py init
python3 scripts/taste_store.py show
python3 scripts/taste_store.py add --type modification --target 酸黄瓜 --action remove \
  --product-code 1100 --text "不要酸黄瓜" --source user_confirm
python3 scripts/taste_store.py add --type combo_choice --target 雪碧 \
  --round-name "选择套餐内饮料" --text "可乐换雪碧"
python3 scripts/taste_store.py remove --id no-pickle
```

## 参考资料

- `references/mcp-customization.md` — 定制参数的真实结构与实测样例（含 payload 正确/错误对照）
- `references/taste-schema.md` — 口味库 schema、匹配与置信度规则

## MVP 范围

**已跑通**：单品定制（去配料、选口味）、套餐内子项替换（换饮料 / 换小食）、套餐子项本身的单品定制——三者可叠加，实测算价通过。子项特调偶发客户端校验报错，非必现，见降级矩阵。离线回归 20/20 通过。

**留作迭代**：整单复用（上一单整个再来一次）、门店维度偏好、时段/场景偏好（早餐 vs 夜宵）。
