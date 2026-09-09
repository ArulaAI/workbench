"""Document entry points and explicit source relationships."""

LABELS = {"prd": "PRD", "design": "Design spec", "rfc": "RFC"}
SOURCE_KINDS = {"brief": (), "prd": ("prd",), "design": ("design",), "prd_design": ("prd", "design")}


def intake_for(state, kind):
    # Keep the original PRD intake readable without rewriting saved workspaces.
    return state.get("intake") if kind == "prd" else state.get("intakes", {}).get(kind)


def set_intake(state, kind, intake):
    if kind == "prd":
        state["intake"] = intake
    else:
        state.setdefault("intakes", {})[kind] = intake


def mode_for(pins):
    return next(mode for mode, kinds in SOURCE_KINDS.items() if set(kinds) == set(pins))
