"""fallbackchain —— 把模型降级与回退策略写成可验证的规则。

设计原则：
1. **降级可以，输出契约不能变**。切换到备用模型时，下游还得能用。
2. **验证策略本身**，不执行调用。每级的触发条件、输出契约、终止条件都要对得上。
3. **终止条件必须存在**。没有终止条件的回退链就是无限循环。

仅依赖 Python 标准库。

用法:
    python fallbackchain.py --help
    python fallbackchain.py --policy policy.json
    python fallbackchain.py --policy policy.json --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# 策略格式
# ---------------------------------------------------------------------------

# 期望的策略结构：
# {
#   "levels": [
#     {"name":"primary","model":"gpt-4o",
#      "trigger":{"on":["timeout","error"],"within_ms":30000},
#      "output_contract":{"type":"json","required":["answer","sources"]},
#      "terminal": false},
#     {"name":"fallback","model":"claude-3-5-sonnet",
#      "trigger":{"on":["timeout","error"]},
#      "output_contract":{"type":"json","required":["answer","sources"]},
#      "terminal": true}
#   ]
# }

REQUIRED_FIELDS = ("name", "model", "trigger", "output_contract", "terminal")


def load_policy(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"读不了策略文件 {path}：{e}") from e
    if not isinstance(data, dict):
        raise ValueError("策略文件应该是一个 JSON 对象")
    return data


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def contract_signature(contract: dict) -> str:
    """把输出契约归一成一个可比较的签名。"""
    if not isinstance(contract, dict):
        return "invalid"
    parts = [
        f"type={contract.get('type', '?')}",
        f"required={','.join(sorted(contract.get('required') or []))}",
        f"optional={','.join(sorted(contract.get('optional') or []))}",
        f"nullable={contract.get('nullable', False)}",
    ]
    return "|".join(parts)


def validate(policy: dict) -> dict:
    """校验一套回退策略。"""
    levels = policy.get("levels") or []
    findings: list[dict] = []

    if not levels:
        return {"levels": 0, "findings": [{"kind": "empty_policy", "severity": 3,
                                           "detail": "策略里没有任何级别"}],
                "contracts": [], "summary": {"issue_count": 1}}

    # 逐级检查字段完整性
    for i, lvl in enumerate(levels):
        missing = [f for f in REQUIRED_FIELDS if f not in lvl]
        if missing:
            findings.append({
                "kind": "missing_fields",
                "severity": 3,
                "level": lvl.get("name", f"#{i + 1}"),
                "detail": f"缺少字段：{'、'.join(missing)}",
            })

        trigger = lvl.get("trigger") or {}
        if isinstance(trigger, dict):
            if not trigger.get("on"):
                findings.append({
                    "kind": "empty_trigger",
                    "severity": 2,
                    "level": lvl.get("name", f"#{i + 1}"),
                    "detail": "没有声明触发条件（trigger.on）",
                })
            within = trigger.get("within_ms")
            if isinstance(within, (int, float)) and within <= 0:
                findings.append({
                    "kind": "bad_timeout",
                    "severity": 3,
                    "level": lvl.get("name", f"#{i + 1}"),
                    "detail": f"超时时间 {within} 不是正数",
                })
        elif "trigger" in lvl:
            findings.append({
                "kind": "bad_trigger_shape",
                "severity": 2,
                "level": lvl.get("name", f"#{i + 1}"),
                "detail": "trigger 应该是对象",
            })

        contract = lvl.get("output_contract")
        if contract is not None and not isinstance(contract, dict):
            findings.append({
                "kind": "bad_contract_shape",
                "severity": 3,
                "level": lvl.get("name", f"#{i + 1}"),
                "detail": "output_contract 应该是对象",
            })

    # 终止条件：最后一级必须是 terminal
    last = levels[-1]
    if not last.get("terminal"):
        findings.append({
            "kind": "no_terminal",
            "severity": 3,
            "level": last.get("name", "最后一级"),
            "detail": "最后一级没有标记为 terminal，回退链没有终点",
        })

    # 中间级不该是 terminal（否则后面的级永远到不了）
    for lvl in levels[:-1]:
        if lvl.get("terminal"):
            findings.append({
                "kind": "early_terminal",
                "severity": 2,
                "level": lvl.get("name", ""),
                "detail": "非最后一级标记为 terminal，后面的级别将无法到达",
            })

    # 各级之间的衔接：下一级要覆盖上一级可能触发的条件
    for i in range(len(levels) - 1):
        cur = levels[i]
        nxt = levels[i + 1]
        cur_on = set((cur.get("trigger") or {}).get("on") or [])
        next_on = set((nxt.get("trigger") or {}).get("on") or [])
        if cur_on and next_on and not (cur_on & next_on):
            findings.append({
                "kind": "trigger_gap",
                "severity": 2,
                "level": f"{cur.get('name', '')} → {nxt.get('name', '')}",
                "detail": f"上一级能因 {'、'.join(sorted(cur_on))} 触发，"
                          f"下一级却只处理 {'、'.join(sorted(next_on))}——"
                          f"中间有条件没人接",
            })

    # 输出契约一致性：各级必须能互换
    contracts = []
    for lvl in levels:
        contracts.append({
            "level": lvl.get("name", ""),
            "model": lvl.get("model", ""),
            "signature": contract_signature(lvl.get("output_contract") or {}),
            "terminal": bool(lvl.get("terminal")),
        })

    base_sig = contracts[0]["signature"] if contracts else ""
    for c in contracts[1:]:
        if c["signature"] != base_sig:
            findings.append({
                "kind": "contract_mismatch",
                "severity": 3,
                "level": c["level"],
                "detail": f"输出契约与第一级不一致：{c['signature']} ≠ {base_sig}",
            })

    # 契约本身缺字段
    for lvl in levels:
        contract = lvl.get("output_contract")
        if isinstance(contract, dict):
            if not contract.get("type"):
                findings.append({
                    "kind": "contract_no_type",
                    "severity": 2,
                    "level": lvl.get("name", ""),
                    "detail": "输出契约没有声明 type",
                })
            if not contract.get("required"):
                findings.append({
                    "kind": "contract_no_required",
                    "severity": 1,
                    "level": lvl.get("name", ""),
                    "detail": "输出契约没有 required 字段——"
                              "切换模型后下游可能拿不到该有的字段",
                })

    # 模型重复
    models = [lvl.get("model", "") for lvl in levels]
    for m in set(models):
        if models.count(m) > 1:
            findings.append({
                "kind": "duplicate_model",
                "severity": 2,
                "level": "",
                "detail": f"模型 {m} 在链里出现了 {models.count(m)} 次——"
                          f"回退到同一个模型等于没有回退",
            })

    findings.sort(key=lambda f: -f["severity"])
    return {
        "levels": len(levels),
        "findings": findings,
        "contracts": contracts,
        "summary": {
            "issue_count": len(findings),
            "severity_3": sum(1 for f in findings if f["severity"] == 3),
            "severity_2": sum(1 for f in findings if f["severity"] == 2),
            "severity_1": sum(1 for f in findings if f["severity"] == 1),
            "contracts_consistent": all(
                c["signature"] == base_sig for c in contracts) if contracts else False,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render(result: dict) -> str:
    out: list[str] = []
    s = result["summary"]
    out.append("回退策略校验")
    out.append("=" * 60)
    out.append(f"级别数 {result['levels']} ｜ 问题 {s['issue_count']}"
               f"（严重 {s['severity_3']} / 中 {s['severity_2']} / 轻 {s['severity_1']}）")
    out.append("")

    out.append("各级输出契约：")
    for c in result["contracts"]:
        mark = "✓ 一致" if c["signature"] == (
            result["contracts"][0]["signature"] if result["contracts"] else "") else "✗ 不一致"
        term = "  [terminal]" if c["terminal"] else ""
        out.append(f"  {c['level']:<12} {c['model']:<24} {mark}{term}")
        out.append(f"      {c['signature']}")
    out.append("")

    if result["findings"]:
        out.append("问题：")
        for f in result["findings"]:
            sev = {3: "严重", 2: "中", 1: "轻"}.get(f["severity"], "")
            lvl = f"  [{f.get('level')}] " if f.get("level") else "  "
            out.append(f"{lvl}{sev}：{f['detail']}")
        out.append("")
    else:
        out.append("策略本身站得住：每级有触发条件、有输出契约、有终点，"
                   "各级契约一致。")
        out.append("")

    out.append("注：本工具只检查策略写得对不对，不执行任何回退。")
    return "\n".join(out).rstrip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="fallbackchain",
        description="把模型降级与回退策略写成可验证的规则（仅依赖标准库）",
        epilog=(
            "策略文件：\n"
            "  {\"levels\":[{\"name\":\"primary\",\"model\":\"gpt-4o\","
            "\"trigger\":{\"on\":[\"timeout\"],\"within_ms\":30000},"
            "\"output_contract\":{\"type\":\"json\",\"required\":[\"answer\"]},"
            "\"terminal\":false}]}\n"
            "  python fallbackchain.py --policy policy.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--policy", required=True, help="策略文件路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    try:
        policy = load_policy(args.policy)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    result = validate(policy)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(render(result))
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
