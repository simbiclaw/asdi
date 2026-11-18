"""Shared helpers for the asdi-build-verify scripts. Standard library only."""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTER = os.path.join(HERE, "..", "references", "register.json")
STATUSES = ["pass", "fail", "blocked", "error", "not_applicable"]


def load_register():
    with open(REGISTER, encoding="utf-8") as f:
        return json.load(f)


def normalise_target(t):
    t = t.strip().lower().replace("_", "-").replace(" ", "-")
    m = re.fullmatch(r"(?:phase-?)?(\d+)", t)
    if m:
        return "phase-" + m.group(1)
    m = re.fullmatch(r"p(?:ass)?-?2-(\d+)", t)
    if m:
        return "p2-" + m.group(1)
    return {"firstlight": "first-light", "fullloop": "full-loop", "gate": "deploy-gate"}.get(t, t)


def select(reg, target):
    """Rows for a target: its own rows plus every standing row that applies by then."""
    order = reg["build_order"]
    if target == "standing":
        pos = len(order)
    elif target in order:
        pos = order.index(target)
    elif target in reg["pass2_targets"]:
        pos = len(order)
    else:
        raise SystemExit("Unknown target %r. Use one of: %s, %s, standing"
                         % (target, ", ".join(order), ", ".join(reg["pass2_targets"])))
    rows = []
    for r in reg["requirements"]:
        if r["kind"] == "standing":
            if order.index(r["applies_from"]) <= pos:
                rows.append(r)
        elif r.get("target") == target:
            rows.append(r)
    return rows
