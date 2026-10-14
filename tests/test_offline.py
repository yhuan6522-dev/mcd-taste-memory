#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦口味记忆 — 离线回归测试。

不联网、不调 MCP、不动你真实的 ~/.workbuddy/mcd-taste-memory/taste.json
（每个用例都在临时目录里另起一个库）。

跑法：
    python3 tests/test_offline.py          # 简洁
    python3 tests/test_offline.py -v       # 逐条显示

覆盖的是「错了就会下错单」的那几条：
  全量提交 / 同组不能只传一项 / 套餐换子项 / 降级 / 必选项不可去 / 冲突不猜 /
  全局规则需显式放行 / 临时改动不自动升级 / 软删除。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TASTE = os.path.join(SKILL, "scripts", "taste_store.py")
BUILD = os.path.join(SKILL, "scripts", "build_modification.py")
FIX = os.path.join(HERE, "fixtures")

PY = sys.executable


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mcd-test-")
        self.db = os.path.join(self.tmp, "taste.json")
        self.env = dict(os.environ, MCD_TASTE_DB=self.db)
        self.cli([TASTE, "init"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, args, expect_ok=True):
        r = subprocess.run([PY] + args, capture_output=True, text=True, env=self.env)
        if expect_ok and r.returncode != 0:
            raise AssertionError(f"命令失败 {args}\nstdout: {r.stdout}\nstderr: {r.stderr}")
        return r

    def add(self, type_, action, target, **kw):
        cmd = [TASTE, "add", "--type", type_, "--action", action, "--target", target]
        for k in ("text", "product_code", "product_name", "round_name", "source", "id"):
            v = kw.get(k)
            if v is None:
                continue
            flag = "--" + k.replace("_", "-")
            if isinstance(v, list):
                for x in v:
                    cmd += [flag, x]
            else:
                cmd += [flag, v]
        self.cli(cmd)

    def build(self, fixture, *extra, expect_ok=True):
        r = self.cli(
            [BUILD, "--detail-file", os.path.join(FIX, fixture), "--rules-file", self.db, *extra],
            expect_ok=expect_ok,
        )
        return json.loads(r.stdout)

    def read_db(self):
        with open(self.db, encoding="utf-8") as f:
            return json.load(f)

    def write_json(self, path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def rules(self):
        return self.read_db()["rules"]


# ---------------------------------------------------------------- 单品特调

class TestSingleModification(Base):
    def test_remove_pickle_full_group(self):
        """去酸黄瓜：组内 5 项必须全部提交，目标项 key 用 unselectedKey、数量 0。"""
        self.add("modification", "remove", "酸黄瓜", text="不要酸黄瓜",
                 product_code=["1100"], product_name=["巨无霸"])
        out = self.build("single_detail.json")

        self.assertEqual(out["mode"], "single")
        vals = out["modification"]["values"]
        self.assertEqual(len(vals), 5, "有 unselectedKey 的组必须全量提交，否则汉堡只剩面包")
        by_code = {v["code"]: v for v in vals}
        self.assertEqual(by_code["100202"]["key"], "0-0")
        self.assertEqual(by_code["100202"]["quantity"], 0)
        for code in ("100116", "100141", "100168", "100212"):
            self.assertEqual(by_code[code]["key"], "0-1")
            self.assertEqual(by_code[code]["quantity"], 1)
        self.assertIn("modi-酸黄瓜", out["applied"])
        self.assertEqual(out["degraded"], [])

    def test_rule_out_of_scope_not_applied(self):
        """规则绑在别的商品上时，不该越界生效。"""
        self.add("modification", "remove", "酸黄瓜", product_code=["9999"])
        out = self.build("single_detail.json")
        self.assertIsNone(out["modification"])
        self.assertEqual(out["applied"], [])

    def test_global_rule_needs_flag(self):
        """无 scope 的全局规则默认不放行，避免「不要香菜」误伤所有商品。"""
        self.add("modification", "remove", "酸黄瓜")
        off = self.build("single_detail.json")
        self.assertIsNone(off["modification"])
        on = self.build("single_detail.json", "--allow-global")
        self.assertIsNotNone(on["modification"])
        self.assertEqual(on["applied"], ["modi-酸黄瓜"])

    def test_degrade_when_target_gone(self):
        """菜单里没有这项 → 降级并说清楚，不要静默丢掉。"""
        self.add("modification", "remove", "酸黄瓜", product_code=["1100"])
        self.add("modification", "remove", "香菜", product_code=["1100"])
        out = self.build("single_detail.json")
        self.assertIn("modi-酸黄瓜", out["applied"])
        self.assertEqual(len(out["degraded"]), 1)
        self.assertIn("香菜", out["degraded"][0]["reason"])
        self.assertIn("modi-香菜", out["degraded"][0]["ruleId"])

    def test_degrade_when_no_options(self):
        """支持特调但 values 为空（如热美式）→ 不硬凑 payload。"""
        self.add("modification", "remove", "酸黄瓜", product_code=["507368"])
        empty = {"code": "507368", "name": "麦咖啡热美式", "supportModify": True,
                 "modification": {"items": [{"maxValues": 1, "minValues": 1, "values": []}]}}
        p = os.path.join(self.tmp, "empty.json")
        self.write_json(p, empty)
        r = self.cli([BUILD, "--detail-file", p, "--rules-file", self.db])
        out = json.loads(r.stdout)
        self.assertIsNone(out["modification"])
        self.assertTrue(any("无可定制项" in d["reason"] for d in out["degraded"]))

    def test_required_item_cannot_remove(self):
        """无 unselectedKey 的组是必选其一（冰量），remove 应被拒并降级。"""
        self.add("modification", "remove", "标准", product_code=["3050"])
        single = {
            "code": "3050", "name": "可乐中杯", "supportModify": True,
            "modification": {"items": [{"maxValues": 1, "minValues": 1, "values": [
                {"code": "200002", "name": "标准", "selectedQuantity": 1, "selectedKey": "0-1"},
                {"code": "200002", "name": "少冰", "selectedQuantity": 0, "selectedKey": "1-1"},
            ]}]},
        }
        p = os.path.join(self.tmp, "drink.json")
        self.write_json(p, single)
        out = json.loads(self.cli([BUILD, "--detail-file", p, "--rules-file", self.db]).stdout)
        self.assertIsNone(out["modification"])
        # 文案要能指出正确改法（改用 set_option），而不只是说「不能去掉」
        self.assertTrue(any("set_option" in d["reason"] for d in out["degraded"]))

    def test_set_option_uses_live_key(self):
        """少冰的 key 是 1-1，不是推出来的 —— 必须现取。"""
        self.add("modification", "set_option", "少冰", product_code=["3050"])
        single = {
            "code": "3050", "name": "可乐中杯", "supportModify": True,
            "modification": {"items": [{"maxValues": 1, "minValues": 1, "values": [
                {"code": "200002", "name": "标准", "selectedQuantity": 1, "selectedKey": "0-1"},
                {"code": "200002", "name": "去冰", "selectedQuantity": 0, "selectedKey": "0-0"},
                {"code": "200002", "name": "少冰", "selectedQuantity": 0, "selectedKey": "1-1"},
            ]}]},
        }
        p = os.path.join(self.tmp, "drink.json")
        self.write_json(p, single)
        out = json.loads(self.cli([BUILD, "--detail-file", p, "--rules-file", self.db]).stdout)
        vals = out["modification"]["values"]
        self.assertEqual(len(vals), 1, "无 unselectedKey 的组只传选中项")
        self.assertEqual(vals[0], {"code": "200002", "key": "1-1", "quantity": 1})

    def test_conflict_is_not_guessed(self):
        """同一项被要求又去又留 → 交给用户定，不许自己挑一个。"""
        self.add("modification", "remove", "酸黄瓜", id="r-去", product_code=["1100"])
        self.add("modification", "keep", "酸黄瓜", id="r-留", product_code=["1100"])
        out = self.build("single_detail.json")
        self.assertEqual(out["applied"], [])
        self.assertEqual(len(out["conflicts"]), 1)
        self.assertEqual(sorted(out["conflicts"][0]["actions"]), ["keep", "remove"])
        self.assertIsNone(out["modification"])


# ---------------------------------------------------------------- 套餐

class TestCombo(Base):
    def test_replace_drink_and_modify_burger(self):
        """可乐换雪碧 + 汉堡去酸黄瓜，走同一条 roundList。"""
        self.add("combo_choice", "replace", "雪碧", round_name="选择套餐内饮料",
                 text="可乐换雪碧")
        self.add("modification", "remove", "酸黄瓜", text="不要酸黄瓜",
                 product_code=["1100"], product_name=["巨无霸"])
        out = self.build("combo_detail.json")

        self.assertEqual(out["mode"], "combo")
        self.assertEqual(len(out["roundList"]), 3, "脚本全量输出三个 round")
        by_round = {r["round"]: r for r in out["roundList"]}
        self.assertEqual(by_round["1"]["comboItemList"][0]["code"], "1100")
        self.assertTrue(any(v["code"] == "100202" and v["quantity"] == 0
                            for v in by_round["1"]["comboItemList"][0]["modification"]["values"]))
        self.assertEqual(by_round["3"]["comboItemList"][0]["code"], "3060",
                         "套餐内雪碧是中杯 3060，不是单点的 3010")
        self.assertEqual(sorted(out["applied"]), sorted(["comb-雪碧", "modi-酸黄瓜"]))

    def test_round_is_string(self):
        self.add("combo_choice", "replace", "雪碧", round_name="选择套餐内饮料")
        out = self.build("combo_detail.json")
        for r in out["roundList"]:
            self.assertIsInstance(r["round"], str, "round 字段必须是字符串")

    def test_default_when_no_rule(self):
        """没有偏好时，各 round 用默认项，不擅自改。"""
        out = self.build("combo_detail.json")
        codes = [r["comboItemList"][0]["code"] for r in out["roundList"]]
        self.assertEqual(codes, ["1100", "4810", "3050"])
        self.assertEqual(out["applied"], [])

    def test_degrade_when_choice_gone(self):
        """这轮里没有想要的选项 → 退回默认并说明理由。"""
        self.add("combo_choice", "replace", "芬达", round_name="选择套餐内饮料")
        out = self.build("combo_detail.json")
        self.assertEqual(out["roundList"][2]["comboItemList"][0]["code"], "3050")
        self.assertTrue(any("芬达" in d["reason"] for d in out["degraded"]))

    def test_cup_size_matching(self):
        """带杯型时匹配要更严：雪碧大杯 → 3110。"""
        self.add("combo_choice", "replace", "雪碧大杯", round_name="选择套餐内饮料")
        out = self.build("combo_detail.json")
        self.assertEqual(out["roundList"][2]["comboItemList"][0]["code"], "3110")


# ---------------------------------------------------------------- 口味库读写

class TestStore(Base):
    def test_add_rejects_bad_enum(self):
        r = self.cli([TASTE, "add", "--type", "xxx", "--action", "remove",
                      "--target", "酸黄瓜"], expect_ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_duplicate_id_rejected(self):
        self.add("modification", "remove", "酸黄瓜", id="same")
        r = self.cli([TASTE, "add", "--type", "modification", "--action", "remove",
                      "--target", "洋葱粒", "--id", "same"], expect_ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_remove_is_soft_by_default(self):
        self.add("modification", "remove", "酸黄瓜")
        self.cli([TASTE, "remove", "--id", "modi-酸黄瓜"])
        rules = self.rules()
        self.assertEqual(len(rules), 1, "默认停用不删除，历史留痕")
        self.assertEqual(rules[0]["status"], "off")

    def test_remove_hard(self):
        self.add("modification", "remove", "酸黄瓜")
        self.cli([TASTE, "remove", "--id", "modi-酸黄瓜", "--hard"])
        self.assertEqual(self.rules(), [])

    def test_temp_override_not_promoted(self):
        """临时改动只进 tempOverrides，绝不自动改规则。"""
        self.add("modification", "remove", "酸黄瓜")
        self.cli([TASTE, "log-temp", "--rule-id", "modi-酸黄瓜", "--diff", "这次又加了酸黄瓜"])
        db = self.read_db()
        self.assertEqual(len(db["tempOverrides"]), 1)
        self.assertFalse(db["tempOverrides"][0]["resolved"])
        self.assertEqual(db["rules"][0]["action"], "remove", "规则本身没被动过")

        tid = db["tempOverrides"][0]["id"]
        self.cli([TASTE, "promote", "--temp-id", tid, "--action", "keep", "--text", "要酸黄瓜"])
        db = self.read_db()
        self.assertEqual(db["rules"][0]["action"], "keep")
        self.assertEqual(db["rules"][0]["confidence"], "confirmed")
        self.assertTrue(db["tempOverrides"][0]["resolved"])

    def test_apply_increments_hitcount(self):
        self.add("modification", "remove", "酸黄瓜", product_code=["1100"], product_name=["巨无霸"])
        self.build("single_detail.json")
        self.assertEqual(self.rules()[0]["hitCount"], 0, "不加 --apply 不写回")
        self.build("single_detail.json", "--apply")
        db = self.read_db()
        self.assertEqual(db["rules"][0]["hitCount"], 1)
        self.assertEqual(db["stats"]["autoApplied"], 1)

    def test_file_is_valid_json_after_each_write(self):
        self.add("modification", "remove", "酸黄瓜")
        self.cli([TASTE, "log-temp", "--rule-id", "modi-酸黄瓜", "--diff", "x"])
        db = self.read_db()
        for key in ("version", "rules", "tempOverrides", "stats"):
            self.assertIn(key, db)


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
