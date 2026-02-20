import json
import os
from datetime import datetime

from planner.graph import GenGraph
from planner.models import ItemNode, Recipe, RecipeNode, SessionState


def sanitize_filename_component(text: str) -> str:
    invalid = '<>:"/\\|?*'
    normalized = "".join("_" if (ch.isspace() or ch in invalid) else ch for ch in text.strip())
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    normalized = normalized.strip("._")
    return normalized or "session"


def build_session_label(pairs: list[tuple[str, float]]) -> str:
    if len(pairs) == 0:
        return "empty"
    parts = []
    for name, rate in pairs:
        rate_tag = f"{rate:g}".replace(".", "p")
        parts.append(f"{sanitize_filename_component(name)}_{rate_tag}")
    label = "__".join(parts)
    if len(label) > 120:
        label = label[:120].rstrip("_")
    return label or "session"


def infer_label_from_graph(graph: GenGraph) -> str:
    producers, _consumers = graph._build_adjacency()
    roots = []
    for item_id, node in enumerate(graph.item_nodes):
        if not node.active:
            continue
        if len(producers[item_id]) == 0:
            roots.append((node.name, node.rate))
    roots.sort(key=lambda x: x[0])
    return build_session_label(roots[:4])


def graph_to_dict(graph: GenGraph) -> dict:
    return {
        "item_nodes": [
            {"name": n.name, "rate": n.rate, "active": n.active}
            for n in graph.item_nodes
        ],
        "recipe_nodes": [
            {
                "recipe": {
                    "ins": r.recipe.ins,
                    "outs": r.recipe.outs,
                    "machine_name": r.recipe.machine_name,
                    "machine_class": r.recipe.machine_class,
                    "recipe_id": r.recipe.recipe_id,
                },
                "machines": r.machines,
                "machine_name": r.machine_name,
                "in_ids": r.in_ids,
                "out_ids": r.out_ids,
                "active": r.active,
            }
            for r in graph.recipe_nodes
        ],
    }


def graph_from_dict(data: dict) -> GenGraph:
    item_nodes = [
        ItemNode(
            name=item["name"],
            rate=float(item["rate"]),
            active=bool(item.get("active", True)),
        )
        for item in data.get("item_nodes", [])
    ]
    recipe_nodes = []
    for recipe_node in data.get("recipe_nodes", []):
        recipe_data = recipe_node["recipe"]
        recipe = Recipe(
            ins=[(name, float(rate)) for name, rate in recipe_data["ins"]],
            outs=[(name, float(rate)) for name, rate in recipe_data["outs"]],
            machine_name=recipe_data.get("machine_name", "Machine"),
            machine_class=recipe_data.get("machine_class", ""),
            recipe_id=recipe_data.get("recipe_id", ""),
        )
        recipe_nodes.append(
            RecipeNode(
                recipe=recipe,
                machines=float(recipe_node["machines"]),
                machine_name=recipe_node["machine_name"],
                in_ids=[int(x) for x in recipe_node["in_ids"]],
                out_ids=[int(x) for x in recipe_node["out_ids"]],
                active=bool(recipe_node.get("active", True)),
            )
        )
    return GenGraph(item_nodes=item_nodes, recipe_nodes=recipe_nodes)


def save_session(state: SessionState) -> str:
    os.makedirs("sessions", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = sanitize_filename_component(state.label or infer_label_from_graph(state.graph))
    path = os.path.join("sessions", f"{timestamp}_{label}.json")

    payload = {
        "version": 1,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "session_label": label,
        "graph": graph_to_dict(state.graph),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def latest_session_path() -> str | None:
    if not os.path.isdir("sessions"):
        return None
    cands = [
        os.path.join("sessions", name)
        for name in os.listdir("sessions")
        if name.endswith(".json")
    ]
    if len(cands) == 0:
        return None
    return max(cands, key=os.path.getmtime)


def list_session_paths() -> list[str]:
    if not os.path.isdir("sessions"):
        return []
    cands = [
        os.path.join("sessions", name)
        for name in os.listdir("sessions")
        if name.endswith(".json")
    ]
    cands.sort(key=os.path.getmtime, reverse=True)
    return cands


def resolve_session_path(raw: str) -> str | None:
    candidates = [
        raw,
        os.path.join("sessions", raw),
    ]
    if not raw.endswith(".json"):
        candidates.append(f"{raw}.json")
        candidates.append(os.path.join("sessions", f"{raw}.json"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def load_session(path: str) -> SessionState:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    graph = graph_from_dict(payload["graph"])
    label = payload.get("session_label", os.path.splitext(os.path.basename(path))[0])
    return SessionState(graph=graph, label=label)

