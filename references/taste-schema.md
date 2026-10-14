# 口味库 Schema 与匹配规则

路径：`~/.workbuddy/mcd-taste-memory/taste.json`（可用 `MCD_TASTE_DB` 环境变量覆盖）。

## 结构

```json
{
  "version": 1,
  "updatedAt": "2026-10-13T12:40:00+08:00",
  "owner": "本人",
  "rules": [
    {
      "id": "no-pickle",
      "type": "modification",
      "action": "remove",
      "target": "酸黄瓜",
      "scope": { "productCodes": ["1100"], "productNames": ["巨无霸"] },
      "text": "不要酸黄瓜",
      "source": "user_confirm",
      "confidence": "confirmed",
      "hitCount": 4,
      "createdAt": "2026-10-13T12:40:00+08:00",
      "lastAppliedAt": "2026-10-13T12:40:00+08:00",
      "status": "active"
    },
    {
      "id": "sprite-over-cola",
      "type": "combo_choice",
      "action": "replace",
      "target": "雪碧",
      "scope": { "roundName": "选择套餐内饮料" },
      "text": "可乐换雪碧",
      "source": "import",
      "confidence": "confirmed",
      "hitCount": 2,
      "status": "active"
    }
  ],
  "tempOverrides": [
    { "id": "t-20261013-1", "ruleId": "no-pickle", "diff": "本次改为保留酸黄瓜",
      "orderRef": null, "createdAt": "2026-10-13T12:40:00+08:00", "resolved": false }
  ],
  "lastApplied": [
    { "ruleId": "no-pickle", "productCode": "1100", "appliedAt": "2026-10-13T12:40:00+08:00", "ok": true }
  ],
  "stats": { "ordersWithMemory": 0, "autoApplied": 0, "degraded": 0, "userUndone": 0 }
}
```

## 字段说明

### rule.type / action

| type | action | 含义 | 落在哪个参数 |
|---|---|---|---|
| `modification` | `remove` | 去掉某个配料（酸黄瓜、洋葱、糖、奶油球） | 该项用 `unselectedKey`，qty=0 |
| `modification` | `keep` | 明确保留某配料 | 该项用 `selectedKey`，qty=1 |
| `modification` | `set_option` | 单选口味组取值（少冰／去冰／多冰） | 选中项用自己的 `selectedKey` |
| `combo_choice` | `replace` | 套餐内换子项（饮料／小食） | `roundList[].comboItemList[].code` |

> 写规则时最容易搞混的一条：**「少冰」「去冰」是 `set_option`，不是 `remove`**。
> 冰量组是 N 选 1 的口味值，没有 `unselectedKey`，用 remove 写会被降级并提示改法。
> 只有配料类（酸黄瓜、洋葱粒、白砂糖、奶油球）才用 remove。

### scope

- `modification` 类：`productCodes` 优先；拿不到 code 时退到 `productNames`。
- `combo_choice` 类：`roundName` 必填（如「选择套餐内饮料」），运行时在 `rounds[]` 里按名找 round。
- `scope` 为空 = 全局规则（对所有可匹配商品生效），MVP 阶段**慎用**，命中前先确认。

### confidence / source

- `confirmed` — 用户明确确认过（导入时点过头，或事后固化的）。
- `inferred` — 从历史订单频次推断，未经确认。**导入流程必须把它们摆出来让用户过目，过目后转 `confirmed`。**
- `source`：`import`（历史订单）/ `user_confirm`（建档确认）/ `observed`（多次观察后询问确认）。

### status

`active` / `stale`（商品或选项已失效，保留不套用，供日后商品回归时复活）/ `off`（用户主动关掉）。

## 匹配算法

对当前要下单的每个商品：

1. **取 detail** — `query-meal-detail` 拿 `modification` 与 `rounds`。
2. **筛规则** — `status=active` 且 scope 命中：
   - `modification`：`productCode ∈ scope.productCodes`，或 `productName ∈ scope.productNames`
   - `combo_choice`：当前套餐存在 `rounds[].name == scope.roundName`
3. **校验可用性** — 在 detail 里按 `target` 名字找对应项：
   - `modification`：在任一组 `values[].name` 中精确匹配到 `target`
   - `combo_choice`：在该 round 的 `choices[].name` 中匹配（先精确，再退化为包含匹配；含杯型诉求时要求同时命中杯型词）
   - 找不到 → 降级，计入 `degraded`，**明确告知用户哪条没生效**
4. **构建** — 交给 `scripts/build_modification.py`，不要手拼。
5. **无命中** — 不生成 `modification`，保持默认。

## 冲突处理

同一组内同时存在 `remove`（去酸黄瓜）与 `keep`（要酸黄瓜）→ 不猜，直接问。
同一 round 内多条 `combo_choice` 命中不同目标 → 同上。

## 计数与沉淀

- 每次成功套用：`hitCount += 1`，写 `lastAppliedAt`。
- 套用后用户撤销某条：`userUndone += 1`。同一条被撤销 3 次以上 → 主动问是否 `status=off`，不要默默继续套。
- `tempOverrides` 里同一 ruleId 累计 2 次相同 diff → 主动问「要不要把这次改动变成长久习惯」。
