#!/usr/bin/env python3
"""把口味规则编译成麦当劳 MCP 的 modification / roundList 参数。

不要手拼 payload —— 同组全量提交、key 实时取值这两条最容易错，交给这里。

用法：
  python3 build_modification.py --detail-file /tmp/detail.json [--rules-file ~/.workbuddy/mcd-taste-memory/taste.json] [--apply]

--detail-file 里放 query-meal-detail 的原始返回（整包或 data 对象都认）。
输出 JSON 到 stdout，包含可直接塞进 items[] 的字段，以及 applied / degraded 明细。
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import taste_store  # noqa: E402


def load_detail(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get("data", raw) if isinstance(raw, dict) else raw


def norm(s):
    return (s or "").replace(" ", "").strip()


def pick_choice(choices, target):
    """套餐里按名字选子项。精确优先，再退化包含匹配；含杯型词时要求杯型也命中。"""
    t = norm(target)
    for c in choices:
        if norm(c.get("name")) == t:
            return c
    cup = next((w for w in ("大杯", "中杯", "小杯") if w in t), None)
    fuzzy = []
    for c in choices:
        n = norm(c.get("name"))
        if t in n or (cup and cup in n and t.replace(cup, "") in n):
            fuzzy.append(c)
    if fuzzy:
        # 名字越短越接近精确命中：否则「可乐」会先撞上「无糖可口可乐中杯」
        return min(fuzzy, key=lambda c: len(norm(c.get("name"))))
    return None


def build_group_values(group, chosen):
    """按组生成 values 数组。chosen: {index: (key, quantity)}

    - 有 unselectedKey 的组（可增减配料）：组内每一项都输出（未选用 unselectedKey，qty=0）
    - 无 unselectedKey 的组（单选口味值）：只输出一项——命中就输出命中项，没命中就输出当前默认项。
      这类组语义是「N 选 1」，多传一项 = 同时点了两个口味值。
    """
    vs = group.get("values", [])
    if not any(v.get("unselectedKey") for v in vs):
        if chosen:
            return [
                {"code": vs[i]["code"], "key": key, "quantity": qty}
                for i, (key, qty) in sorted(chosen.items())
            ]
        return [
            {"code": v["code"], "key": v["selectedKey"], "quantity": v.get("selectedQuantity", 1)}
            for v in vs
            if v.get("selectedQuantity", 0) and v.get("selectedKey")
        ]

    values = []
    for i, v in enumerate(group.get("values", [])):
        if i in chosen:
            key, qty = chosen[i]
            values.append({"code": v["code"], "key": key, "quantity": qty})
            continue
        if v.get("selectedQuantity", 0) and v.get("selectedKey"):
            values.append(
                {"code": v["code"], "key": v["selectedKey"], "quantity": v.get("selectedQuantity", 1)}
            )
        elif v.get("unselectedKey"):
            values.append({"code": v["code"], "key": v["unselectedKey"], "quantity": 0})
    return values


def apply_modification_rules(mod, rules, applied, degraded, conflicts=None):
    """对单个商品的 modification 应用规则，返回 payload 或 None。

    同一特调项被多条规则以矛盾方式命中时，不猜：整项跳过，交回用户定夺。
    """
    conflicts = conflicts if conflicts is not None else []
    items = (mod or {}).get("items") or []
    # supportModify=true 但 values 全空（如麦咖啡热美式）也算「无可定制项」，别硬凑 payload
    has_options = any(g.get("values") for g in items)
    if not items or not has_options:
        for r in rules:
            degraded.append({"ruleId": r["id"], "reason": "该商品当前无可定制项，已按默认"})
        return None

    # 第一轮：定位命中项，把打在同一项上的规则归拢
    hits = {}  # (组下标, 项下标) -> [(rule, value, action)]
    for r in rules:
        hit = None
        for gi, g in enumerate(items):
            for vi, v in enumerate(g.get("values", [])):
                if norm(v.get("name")) == norm(r["target"]):
                    hit = (gi, vi, v)
                    break
            if hit:
                break
        if not hit:
            degraded.append(
                {"ruleId": r["id"], "reason": f"当前菜单没有「{r['target']}」这一项，该偏好本次未生效"}
            )
            continue
        gi, vi, v = hit
        hits.setdefault((gi, vi), []).append((r, v, r["action"]))

    # 第二轮：冲突的整项放弃，其余落定
    chosen = {}  # {组下标: {项下标: (key, quantity)}}
    for (gi, vi), entries in hits.items():
        acts = {a for _, _, a in entries}
        contradictory = len(acts) > 1 and bool(acts & {"remove"}) and bool(acts & {"keep", "set_option"})
        if len(entries) > 1 and (contradictory or len(acts) > 1):
            conflicts.append(
                {
                    "target": entries[0][1].get("name"),
                    "ruleIds": [r["id"] for r, _, _ in entries],
                    "actions": sorted(acts),
                    "reason": "这几条偏好互相矛盾，本次保持默认，需要你定一个",
                }
            )
            continue
        r, v, action = entries[0]
        if action == "remove":
            if not v.get("unselectedKey"):
                # 冰量、甜度这类是「N 选 1 的口味值」，不是能删掉的配料
                degraded.append(
                    {
                        "ruleId": r["id"],
                        "reason": (
                            f"「{r['target']}」是单选口味值，不是能去掉的配料。"
                            f"想选它请把这条改成 set_option，本次保留默认"
                        ),
                    }
                )
                continue
            chosen.setdefault(gi, {})[vi] = (v["unselectedKey"], 0)
        elif action in ("keep", "set_option"):
            if not v.get("selectedKey"):
                degraded.append({"ruleId": r["id"], "reason": f"「{r['target']}」缺少 selectedKey，已跳过"})
                continue
            chosen.setdefault(gi, {})[vi] = (v["selectedKey"], 1)
        else:
            degraded.append({"ruleId": r["id"], "reason": f"不支持的 action：{r['action']}"})
            continue
        applied.append(r["id"])

    if not chosen:
        return None

    values = []
    for gi, g in enumerate(items):
        values.extend(build_group_values(g, chosen.get(gi, {})))
    return {"values": values} if values else None


def match_mod_rules(db, product_code, product_name, allow_global):
    out = []
    for r in db.get("rules", []):
        if r.get("status") != "active" or r.get("type") != "modification":
            continue
        codes = r.get("scope", {}).get("productCodes") or []
        names = r.get("scope", {}).get("productNames") or []
        if product_code and product_code in codes:
            out.append(r)
        elif product_name and product_name in names:
            out.append(r)
        elif not codes and not names and allow_global:
            out.append(r)
    return out


def main():
    p = argparse.ArgumentParser(description="口味规则 → MCP 定制参数")
    p.add_argument("--detail-file", required=True)
    p.add_argument("--rules-file")
    p.add_argument("--allow-global", action="store_true", help="允许无 scope 的全局规则生效")
    p.add_argument("--apply", action="store_true", help="同时回写命中计数")
    args = p.parse_args()

    if args.rules_file:
        taste_store.DB_PATH = args.rules_file
    db = taste_store.load()
    detail = load_detail(args.detail_file)

    applied, degraded, conflicts = [], [], []
    result = {"productCode": detail.get("code"), "name": detail.get("name")}

    if detail.get("rounds"):
        result["mode"] = "combo"
        round_list = []
        for rd in detail["rounds"]:
            choices = rd.get("choices") or []
            picked = None
            # 一个 round 只能挑一个子项，先把打在这个 round 上的规则全收出来
            round_rules = [
                r
                for r in db.get("rules", [])
                if r.get("status") == "active"
                and r.get("type") == "combo_choice"
                and norm(r.get("scope", {}).get("roundName")) == norm(rd.get("name"))
            ]
            if round_rules:
                targets = {norm(r["target"]) for r in round_rules}
                if len(targets) > 1:
                    conflicts.append(
                        {
                            "target": rd.get("name"),
                            "ruleIds": [r["id"] for r in round_rules],
                            "actions": sorted({r["action"] for r in round_rules}),
                            "reason": f"「{rd.get('name')}」只能选一个，这几条指向不同选项，本次保持默认",
                        }
                    )
                else:
                    r = round_rules[0]
                    c = pick_choice(choices, r["target"])
                    if c:
                        picked = c
                        applied.append(r["id"])
                    else:
                        degraded.append(
                            {
                                "ruleId": r["id"],
                                "reason": f"「{rd.get('name')}」里现在没有「{r['target']}」，已用默认",
                            }
                        )
            if picked is None:
                picked = next((c for c in choices if c.get("isDefault") == 1), choices[0] if choices else None)
            if picked is None:
                continue

            entry = {"code": picked["code"], "quantity": rd.get("quantity") or 1}
            sub_rules = match_mod_rules(db, picked.get("code"), picked.get("name"), args.allow_global)
            if sub_rules:
                sub = apply_modification_rules(
                    picked.get("modification"), sub_rules, applied, degraded, conflicts
                )
                if sub:
                    entry["modification"] = sub
            round_list.append({"round": str(rd.get("id")), "comboItemList": [entry]})
        result["roundList"] = round_list
        result["modification"] = None
    else:
        result["mode"] = "single"
        rules = match_mod_rules(db, detail.get("code"), detail.get("name"), args.allow_global)
        result["modification"] = apply_modification_rules(
            detail.get("modification"), rules, applied, degraded, conflicts
        )
        result["roundList"] = None

    result["applied"] = applied
    result["degraded"] = degraded
    result["conflicts"] = conflicts

    if args.apply and applied:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        for rid in applied:
            for r in db.get("rules", []):
                if r["id"] == rid:
                    r["hitCount"] = r.get("hitCount", 0) + 1
                    r["lastAppliedAt"] = stamp
        db.setdefault("stats", {})
        db["stats"]["autoApplied"] = db["stats"].get("autoApplied", 0) + len(applied)
        db["stats"]["degraded"] = db["stats"].get("degraded", 0) + len(degraded)
        taste_store.save(db)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
