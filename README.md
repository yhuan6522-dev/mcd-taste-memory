# mcd-taste-memory

麦当劳点餐的**口味记忆层**。记住你的定制偏好——不要酸黄瓜、可乐换雪碧、咖啡少冰——下单时自动套用，选项失效时降级为默认并明确告知，临时改动绝不自动升级成长期习惯。

麦当劳 MCP 提供点餐能力，但不提供「偏好存储」。这个 Skill 补的就是这一层：一个本地 JSON 口味库 + 一个把偏好编译成 MCP 参数的脚本。

## 它解决什么

每次点麦当劳都要重复说一遍「不要酸黄瓜」。更麻烦的是，定制参数的构造有坑：

- 有 `unselectedKey` 的特调组必须**全量提交**。只传「酸黄瓜：不要」，服务端会把组内其余配料判为未选——汉堡只剩面包和肉饼。
- `key` 不是通用编码。「少冰」是 `1-1`，「多冰」是 `0-2`，必须每次现取。
- 「可乐换雪碧」不是特调，是换套餐里的 round 子项；同一个雪碧在单点和套餐里是三个不同 code。

这些规则写进脚本里，不再靠模型临场拼 payload。

## 目录

```
mcd-taste-memory/
├── SKILL.md                        # 给 agent 看的流程与硬性规则
├── scripts/
│   ├── taste_store.py              # 口味库读写（纯本地 JSON）
│   └── build_modification.py       # 偏好 → MCP modification / roundList
├── references/
│   ├── mcp-customization.md        # 定制参数真实结构 + 实测样例 + 非必现报错
│   └── taste-schema.md             # 口味库 schema、匹配与置信度
└── tests/
    ├── test_offline.py             # 20 条离线回归用例
    └── fixtures/                   # 真实 query-meal-detail 返回（已裁剪）
```

## 安装

放进技能目录即可：

```bash
git clone <your-repo> ~/.workbuddy/skills/mcd-taste-memory
```

需要 Python 3.9+，无第三方依赖。

## 用法

```bash
# 建档
python3 scripts/taste_store.py init
python3 scripts/taste_store.py add --type modification --action remove --target 酸黄瓜 \
  --product-code 1100 --product-name 巨无霸 --text "不要酸黄瓜"
python3 scripts/taste_store.py add --type combo_choice --action replace --target 雪碧 \
  --round-name "选择套餐内饮料" --text "可乐换雪碧"

# 查看 / 停用（默认软删除，保留历史）
python3 scripts/taste_store.py show
python3 scripts/taste_store.py remove --id modi-酸黄瓜

# 把 query-meal-detail 的返回存成文件，编译出可直接塞进 items[] 的参数
python3 scripts/build_modification.py --detail-file /tmp/detail.json
```

输出包含 `modification` / `roundList`，以及三条说明：`applied`（哪些生效了）、`degraded`（哪些没生效、为什么）、`conflicts`（哪些互相打架，需要人定夺）。

口味库默认在 `~/.workbuddy/mcd-taste-memory/taste.json`，可用 `MCD_TASTE_DB` 环境变量改路径。

## 测试

```bash
python3 tests/test_offline.py -v
```

离线运行：不联网、不调 MCP、不碰你真实的口味库（每个用例在临时目录另起一个库）。覆盖的是「错了就会下错单」的那几条——全量提交、套餐换子项、降级、必选项不可去、冲突不猜、全局规则需显式放行、临时改动不自动升级、软删除。

## 已知限制

- **子项特调偶发 `root: must be object`**：`items[].roundList[].comboItemList[].modification` 偶发被客户端参数校验拒绝，但同一结构多次实测成功（含 16:57 的逐字复测返回 200），属非必现。遇到时只重试一次，仍失败则换子项照做、子项特调降级并告知用户。详见 `references/mcp-customization.md` 第三节。
- **历史订单无特调数据**：`order-list` 响应未声明 modification 字段，单品级特调无法从历史回溯，建档时走冷启动问卷。
- **create-order 未下过实单**：算价端已验证 payload 合法、差价生效，风险已从「未知」降到「低」。首次使用建议用一单小额到店自提跑通。

## 数据来源

`references/mcp-customization.md` 里的结构与结论来自 2026-10-13 的实机调用（门店 3570183，到店自提），不是推测。fixtures 是同一次抓取的真实返回，饮料轮次做了裁剪。

## License

MIT
