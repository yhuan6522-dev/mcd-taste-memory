# 麦当劳 MCP 定制参数实测手册

所有结论来自 2026-10-13 实机调用（门店 3570183，到店自提 orderType=1 / beType=1），非推测。

## 一、定制在数据里长什么样

`query-meal-detail` 返回 `data.modification`（单品）与 `data.rounds[].choices[].modification`（套餐子项）：

```json
"modification": {
  "items": [
    {
      "maxValues": 5, "minValues": 0,
      "values": [
        {"code":"100116","price":0,"name":"巨无霸酱","maxQuantity":1,"minQuantity":0,"selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"},
        {"code":"100141","price":0,"name":"吉士",   "selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"},
        {"code":"100168","price":0,"name":"生菜",   "selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"},
        {"code":"100202","price":0,"name":"酸黄瓜", "selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"},
        {"code":"100212","price":0,"name":"洋葱粒", "selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"}
      ]
    }
  ]
}
```

一个 `items[]` 元素 = 一个特调组。看懂三点就能写对 payload：

### 1. 有 `unselectedKey` 的组 =「可增减配料」，全量提交

巨无霸配料组就是这类。语义是「这一组里每一项当前是什么状态」，所以**组内每一项都要传**：

- 保留 → `{code, key: selectedKey, quantity: 1}`
- 去掉 → `{code, key: unselectedKey, quantity: 0}`

**不要酸黄瓜** 的正确 payload：

```json
"modification": {"values": [
  {"code":"100116","key":"0-1","quantity":1},
  {"code":"100141","key":"0-1","quantity":1},
  {"code":"100168","key":"0-1","quantity":1},
  {"code":"100202","key":"0-0","quantity":0},
  {"code":"100212","key":"0-1","quantity":1}
]}
```

错误写法（最常见的坑）——只传目标项：

```json
"modification": {"values": [{"code":"100202","key":"0-0","quantity":0}]}
```

组内其余配料会因缺失而被判为未选，汉堡只剩面包和肉饼。

### 2. 无 `unselectedKey` 的组 =「单选口味值」，key 是值本身

冰量组（饮料），四项共用同一个 `code`，靠 key 区分：

```json
{"maxValues":1,"minValues":1,"values":[
  {"code":"200002","name":"标准","selectedQuantity":1,"selectedKey":"0-1"},
  {"code":"200002","name":"去冰","selectedQuantity":0,"selectedKey":"0-0"},
  {"code":"200002","name":"多冰","selectedQuantity":0,"selectedKey":"0-2"},
  {"code":"200002","name":"少冰","selectedQuantity":0,"selectedKey":"1-1"}
]}
```

这类**必选其一**（`minValues=1`），只传选中项即可：少冰 → `{"code":"200002","key":"1-1","quantity":1}`。
注意 key 不是「0=不要 1=要」的通用编码，「少冰」是 `1-1` 而「多冰」是 `0-2`——**必须现取，不能推**。

### 3. `supportModify=true` 但 `values: []`

真实存在（如麦咖啡热美式 `507368`）。表示名义可特调、实际无选项 → 降级为默认，不要尝试构造 payload。

## 二、套餐结构：换饮料靠 round，不靠 modification

巨无霸三件套 `9900005466` 顶层 `supportModify=false`，定制全在子项：

```
rounds[0] 新升级巨无霸      → choices: 1100 巨无霸        supportModify=true  (配料组)
rounds[1] 选择套餐内小食    → choices: 4810 中薯条(默认) / 521901 扭扭薯 / 4437 玉米杯 ...
rounds[2] 选择套餐内饮料    → choices: 3050 可乐中杯(默认) / 3060 雪碧中杯 / 3100 可乐大杯 / 3110 雪碧大杯 ...
```

**「可乐换雪碧」是换 round 里的 choice**，走 `items[].roundList`：

```json
"roundList": [
  {"round":"1","comboItemList":[{"code":"1100","quantity":1,"modification":{"values":[/* 去酸黄瓜 */]}}]},
  {"round":"2","comboItemList":[{"code":"4810","quantity":1}]},
  {"round":"3","comboItemList":[{"code":"3060","quantity":1}]}
]
```

`round` 字段是**字符串**，值取 `rounds[].id`。

### 算价实证（2026-10-13，门店 3570183）

拿巨无霸三件套 `9900005466`（标价 ¥41）跑了三组 `calculate-price`：

| 传入 | 返回 price | 结论 |
|---|---|---|
| 全量 roundList：巨无霸去酸黄瓜 + 中薯条 + 雪碧中杯 `3060` | 4100 | 定制合法；雪碧中杯差价 ¥0，价格不变 |
| 全量 roundList：巨无霸去酸黄瓜 + 中薯条 + 雪碧大杯 `3110` | **4300** | 差价 +¥2 被算进去了，证明替换真被采纳，不是被忽略 |
| 只传 round 3 = 雪碧大杯，省略 round 1/2 | 4300 | 未改动的 round 可以省略，服务端会补默认 |

两点落地结论：

1. **组合定制（子项替换 + 子项特调）在套餐里可以同时生效**，走同一条 `roundList`。
2. 未改动的 round **可以省**——实测算价接受且自动补默认。但本 Skill 的脚本仍然全量输出，不去依赖服务端的补全行为。

### 同一个「雪碧」有三个 code

| 场景 | code |
|---|---|
| 单点雪碧 | `3010` |
| 套餐内中杯 | `3060` |
| 套餐内大杯 | `3110` |

所以口味库**不能存 code**，只能存语义（round 名 + 选项名），运行时在 rounds 里按名字匹配。
带杯型诉求时匹配要更严：「雪碧」→ 优先 `isDefault` 附近的同名项；「雪碧大杯」→ 名字全匹配。

## 三、一个非必现的报错：`root: must be object`

同一天 16:45 左右，`items[].roundList[].comboItemList[].modification` 曾被参数校验拒绝，报 `root: must be object`。**但同一结构后来复测是成功的**，所以它不是既定限制。

| 时间 | 结构（同一门店 3570183） | 结果 |
|---|---|---|
| 12:40 / 16:33 | 全量 roundList：子项替换 + 子项特调 | ✅ 4100 / 4300 |
| 16:45 左右 | 同上 | ❌ `root: must be object` |
| **16:57** | 同上，**逐字相同** | ✅ 4100 |

结论：**payload 没错，麦当劳 API 也没拒**——这一套结构多次成功返回 200。差异更可能出在 MCP 客户端侧的间歇性校验。

### 遇到时的处理（兜底，不是常态）

1. 正常工作流**照常提交**子项特调，不要因为见过一次报错就预先放弃。
2. 若某次真的报 `root: must be object`：**只重试一次**，仍失败就停手。不要改结构硬凑。
3. 降级顺序：
   - 保住换子项（`roundList` 换饮料／小食）——这条通道一直可用，「可乐换雪碧」能落地。
   - 子项特调放弃，明确告知用户。
   - 给两条路：接受默认配料，取餐后在柜台改；或拆成单点（汉堡单品走 `items[].modification`，已验证可用），但失去套餐价——**算完价让用户自己决定**，别替他选。
4. `create-order` 还没实单验证过。若下单时才撞到同样报错，走同一套降级。

> 判断这个报错是否还在：按上表结构调一次 `calculate-price`，返回 200 就没问题。
> 若连续多次复现，再把本节升级为「已知限制」并同步改 SKILL.md 的降级分支。

## 四、未验证项

- `create-order` 的 `items` 结构与 `calculate-price` **完全一致**（含 `modification` / `roundList`）。
  算价端已验证 payload 合法、差价生效，风险已从「未知」降到「低」，但**仍未下过实单**。
  首次上线用一单小额到店自提跑通，别拿大额单试。
- `order-list` 是否返回历史特调：本账号无历史订单，且响应结构未声明 modification 字段 → 判定为「不确定」，按 SKILL.md 降级矩阵处理。

## 五、其它已核实事实

- 无独立购物车工具：`query-meals` → `query-meal-detail` → `calculate-price` → `create-order`。
- `calculate-price` 返回金额单位为**分**，展示要除以 100。
- `create-order` 在 `orderType=1` 时必传 `takeWayCode`，取自 `calculate-price` 返回的 `takeWayList[].code`。
- `query-meal-detail` 的展示约束：`supportModify=true` 要标注【可特调】，但**不要主动展开特调列表**，等用户问再看。口味记忆层不受此约束——套用时可以直接说应用了什么。
- 限流 600 次/分钟；`beType=1`（到店自提）不要传 `beCode`，传了会报错。
