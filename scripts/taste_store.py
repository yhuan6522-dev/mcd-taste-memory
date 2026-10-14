#!/usr/bin/env python3
"""麦麦口味记忆 — 口味库读写。

纯本地 JSON 操作，不联网、不调用 MCP、不删除历史规则（remove 只置 status=off）。
用法见 --help 或 SKILL.md。
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime

DB_PATH = os.environ.get("MCD_TASTE_DB") or os.path.join(
    os.path.expanduser("~"), ".workbuddy", "mcd-taste-memory", "taste.json"
)

EMPTY = {
    "version": 1,
    "updatedAt": None,
    "rules": [],
    "tempOverrides": [],
    "lastApplied": [],
    "stats": {"ordersWithMemory": 0, "autoApplied": 0, "degraded": 0, "userUndone": 0},
}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load():
    if not os.path.exists(DB_PATH):
        return json.loads(json.dumps(EMPTY))
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(
            f"口味库读不了：{DB_PATH} 内容不是合法 JSON（{e}）。\n"
            f"手工修好，或先备份再删掉重新 init —— 不要直接清空，里面有你确认过的偏好。"
        )


def save(db):
    db["updatedAt"] = now()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(DB_PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def slug(text, prefix=""):
    base = "".join(ch for ch in text if ch.isalnum()) or "rule"
    return (prefix + "-" if prefix else "") + base


def cmd_init(_):
    if os.path.exists(DB_PATH):
        print(f"已存在：{DB_PATH}")
        return
    save(json.loads(json.dumps(EMPTY)))
    print(f"口味库已创建：{DB_PATH}")


def cmd_show(_):
    db = load()
    if not db["rules"]:
        print("口味库为空。先建档，或直接 add 一条。")
        return
    print(f"口味库：{DB_PATH}\n")
    for r in db["rules"]:
        mark = {"active": "✓", "stale": "⧗", "off": "✕"}.get(r.get("status"), "?")
        scope = r.get("scope", {})
        where = (
            scope.get("roundName")
            or ",".join(scope.get("productNames", []))
            or ",".join(scope.get("productCodes", []))
            or "全局"
        )
        print(
            f"  {mark} [{r['id']}] {r['text']}  "
            f"({r['type']}/{r['action']} → {r['target']}｜作用于 {where}｜"
            f"{r.get('confidence', 'confirmed')}｜命中 {r.get('hitCount', 0)} 次)"
        )
    pending = [t for t in db.get("tempOverrides", []) if not t.get("resolved")]
    if pending:
        print("\n待确认的临时改动：")
        for t in pending:
            print(f"  · [{t['id']}] {t['diff']}")


def cmd_add(a):
    db = load()
    if a.type not in ("modification", "combo_choice"):
        sys.exit("--type 只能是 modification 或 combo_choice")
    if a.action not in ("remove", "keep", "set_option", "replace"):
        sys.exit("--action 只能是 remove / keep / set_option / replace")
    if a.type == "modification" and a.action == "replace":
        sys.exit("modification 不支持 replace 换套餐子项请用 --type combo_choice")
    if a.type == "combo_choice" and a.action != "replace":
        sys.exit("combo_choice 只支持 replace（换套餐内子项），单品配料用 --type modification")
    scope = {}
    if a.product_code:
        scope["productCodes"] = a.product_code
    if a.product_name:
        scope["productNames"] = a.product_name
    if a.round_name:
        scope["roundName"] = a.round_name
    rid = a.id or slug(a.target, a.type[:4])
    for r in db["rules"]:
        if r["id"] == rid:
            sys.exit(f"规则 {rid} 已存在，用 remove 后重建或直接改 JSON")
    db["rules"].append(
        {
            "id": rid,
            "type": a.type,
            "action": a.action,
            "target": a.target,
            "scope": scope,
            "text": a.text or f"{a.target}",
            "source": a.source,
            "confidence": "confirmed" if a.source == "user_confirm" else "inferred",
            "hitCount": 0,
            "createdAt": now(),
            "lastAppliedAt": None,
            "status": "active",
        }
    )
    save(db)
    print(f"已写入规则：{rid} — {a.text or a.target}")


def cmd_remove(a):
    db = load()
    hit = [r for r in db["rules"] if r["id"] == a.id]
    if not hit:
        sys.exit(f"没有规则 {a.id}")
    if a.hard:
        db["rules"] = [r for r in db["rules"] if r["id"] != a.id]
        print(f"已删除 {a.id}")
    else:
        hit[0]["status"] = "off"
        print(f"已停用 {a.id}（记录保留，可改回 active）")
    save(db)


def cmd_log_temp(a):
    db = load()
    tid = "t-" + datetime.now().strftime("%Y%m%d%H%M%S")
    db.setdefault("tempOverrides", []).append(
        {
            "id": tid,
            "ruleId": a.rule_id,
            "diff": a.diff,
            "orderRef": a.order_ref,
            "createdAt": now(),
            "resolved": False,
        }
    )
    save(db)
    print(f"已记录临时改动 {tid}（未升级为永久偏好）：{a.diff}")


def cmd_promote(a):
    """把某次临时改动确认为长期习惯。只改已有 rule 的 target/action/text，不新增。"""
    db = load()
    temp = next((t for t in db.get("tempOverrides", []) if t["id"] == a.temp_id), None)
    if not temp:
        sys.exit(f"没有临时改动 {a.temp_id}")
    rule = next((r for r in db["rules"] if r["id"] == temp["ruleId"]), None)
    if not rule:
        sys.exit(f"找不到关联规则 {temp['ruleId']}")
    if a.action:
        rule["action"] = a.action
    if a.target:
        rule["target"] = a.target
    if a.text:
        rule["text"] = a.text
    rule["source"] = "user_confirm"
    rule["confidence"] = "confirmed"
    rule["status"] = "active"
    temp["resolved"] = True
    save(db)
    print(f"已固化：{rule['id']} → {rule['text']}")


def cmd_stats(_):
    db = load()
    s = db.get("stats", {})
    print(f"口味库：{DB_PATH}")
    print(f"  规则 {len(db['rules'])} 条（生效 {sum(1 for r in db['rules'] if r.get('status') == 'active')}）")
    for k, v in s.items():
        print(f"  {k}: {v}")


def main():
    p = argparse.ArgumentParser(description="麦麦口味记忆 — 口味库读写")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="创建空口味库").set_defaults(func=cmd_init)
    sub.add_parser("show", help="列出全部规则").set_defaults(func=cmd_show)
    sub.add_parser("stats", help="统计").set_defaults(func=cmd_stats)

    a = sub.add_parser("add", help="新增规则")
    a.add_argument("--type", required=True)
    a.add_argument("--action", required=True)
    a.add_argument("--target", required=True, help="特调项名，如 酸黄瓜 / 雪碧 / 少冰")
    a.add_argument("--text", help="给人类看的一句话，如 不要酸黄瓜")
    a.add_argument("--product-code", action="append")
    a.add_argument("--product-name", action="append")
    a.add_argument("--round-name", help="套餐轮次名，如 选择套餐内饮料")
    a.add_argument("--source", default="user_confirm", choices=["import", "user_confirm", "observed"])
    a.add_argument("--id")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("remove", help="停用或删除规则")
    r.add_argument("--id", required=True)
    r.add_argument("--hard", action="store_true", help="真删除，默认只停用")
    r.set_defaults(func=cmd_remove)

    t = sub.add_parser("log-temp", help="记录一次临时改动（不自动升级为偏好）")
    t.add_argument("--rule-id", required=True)
    t.add_argument("--diff", required=True)
    t.add_argument("--order-ref")
    t.set_defaults(func=cmd_log_temp)

    m = sub.add_parser("promote", help="把临时改动确认为长期习惯")
    m.add_argument("--temp-id", required=True)
    m.add_argument("--action")
    m.add_argument("--target")
    m.add_argument("--text")
    m.set_defaults(func=cmd_promote)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
