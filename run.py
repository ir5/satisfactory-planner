import copy
import csv
import json
import os
import sys
from datetime import datetime
from collections import defaultdict, deque
from dataclasses import dataclass

import graphviz
try:
    from colorama import Fore, Style, init as colorama_init
except Exception:
    Fore = None
    Style = None

    def colorama_init(*_args, **_kwargs):
        return None


@dataclass
class Recipe:
    ins: list[tuple[str, float]]
    outs: list[tuple[str, float]]
    machine_name: str = "Machine"
    machine_class: str = ""
    recipe_id: str = ""

    def str(self):
        instr = " ".join(f"{name} {rate:.2f}/min" for name, rate in self.ins)
        outstr = " ".join(f"{name} {rate:.2f}/min" for name, rate in self.outs)
        return f"{instr} ==> {outstr}"


@dataclass
class ItemNode:
    name: str
    rate: float
    active: bool = True

    def label(self, node_id: int):
        return f"[{node_id}]\n{self.rate:.5f}/min\n{self.name}"


@dataclass
class RecipeNode:
    recipe: Recipe
    machines: float
    machine_name: str
    in_ids: list[int]
    out_ids: list[int]
    active: bool = True

    def label(self):
        return f"{self.machine_name}\nx{self.machines:.9f}"


WORKBENCH_CLASS = "/Game/FactoryGame/Buildable/-Shared/WorkBench/BP_WorkshopComponent.BP_WorkshopComponent_C"
AUTOMATED_WORKBENCH_CLASS = "/Game/FactoryGame/Buildable/Factory/AutomatedWorkBench/Build_AutomatedWorkBench.Build_AutomatedWorkBench_C"
BUILD_GUN_CLASS = "/Script/FactoryGame.FGBuildGun"
PARTICLE_ACCELERATOR_CLASS = "/Game/FactoryGame/Buildable/Factory/HadronCollider/Build_HadronCollider.Build_HadronCollider_C"
QUANTUM_ENCODER_CLASS = "/Game/FactoryGame/Buildable/Factory/QuantumEncoder/Build_QuantumEncoder.Build_QuantumEncoder_C"
CONVERTER_CLASS = "/Game/FactoryGame/Buildable/Factory/Converter/Build_Converter.Build_Converter_C"


@dataclass
class PowerModel:
    power_used_by_machine_class: dict[str, float]
    power_used_recipes_by_machine_class: dict[str, dict[str, tuple[float, float]]]

    def power_per_machine_mw(self, recipe: Recipe) -> float:
        machine_class = recipe.machine_class
        if machine_class == "":
            legacy_name_power = {
                "Assembler": 15.0,
                "Blender": 75.0,
                "Constructor": 4.0,
                "Foundry": 16.0,
                "Manufacturer": 55.0,
                "Smelter": 4.0,
                "Packager": 10.0,
                "OilRefinery": 30.0,
                "OilPump": 40.0,
                "WaterPump": 20.0,
                "Miner": 5.0,
                "MinerMk2": 15.0,
                "MinerMk3": 45.0,
                "HadronCollider": 500.0,
                "QuantumEncoder": 1000.0,
                "Converter": 250.0,
            }
            if recipe.machine_name in legacy_name_power:
                return legacy_name_power[recipe.machine_name]
        if machine_class in {"", WORKBENCH_CLASS, AUTOMATED_WORKBENCH_CLASS, BUILD_GUN_CLASS}:
            return 0.0
        if machine_class == QUANTUM_ENCODER_CLASS:
            return 1000.0
        if machine_class == CONVERTER_CLASS:
            return 250.0

        if machine_class == PARTICLE_ACCELERATOR_CLASS:
            ranges = self.power_used_recipes_by_machine_class.get(machine_class, {})
            entry = ranges.get(recipe.recipe_id)
            if entry is not None:
                lo, hi = entry
                return 0.5 * (lo + hi)
            return 500.0

        if machine_class in self.power_used_by_machine_class:
            return float(self.power_used_by_machine_class[machine_class])

        ranges = self.power_used_recipes_by_machine_class.get(machine_class, {})
        entry = ranges.get(recipe.recipe_id)
        if entry is not None:
            lo, hi = entry
            return 0.5 * (lo + hi)
        return 0.0


@dataclass
class GenGraph:
    item_nodes: list[ItemNode]
    recipe_nodes: list[RecipeNode]

    def _is_valid_item(self, item_id: int) -> bool:
        return 0 <= item_id < len(self.item_nodes) and self.item_nodes[item_id].active

    def _build_adjacency(self):
        producers = defaultdict(list)
        consumers = defaultdict(list)
        for recipe_id, recipe_node in enumerate(self.recipe_nodes):
            if not recipe_node.active:
                continue
            for out_id in recipe_node.out_ids:
                if self._is_valid_item(out_id):
                    producers[out_id].append(recipe_id)
            for in_id in recipe_node.in_ids:
                if self._is_valid_item(in_id):
                    consumers[in_id].append(recipe_id)
        return producers, consumers

    def list_active_items(self) -> list[str]:
        producers, consumers = self._build_adjacency()
        lines = []
        for item_id, node in enumerate(self.item_nodes):
            if not node.active:
                continue
            tags = []
            if len(producers[item_id]) == 0:
                tags.append("expandable")
            if len(producers[item_id]) == 0 and len(consumers[item_id]) > 0:
                tags.append("leaf")
            tag_str = ""
            if tags:
                tag_str = f" ({', '.join(tags)})"
            lines.append(f"[{item_id}] {node.name} {node.rate:.5f}/min{tag_str}")
        return lines

    def expand(self, item_node_id: int, recipe: Recipe) -> tuple[bool, str]:
        if not self._is_valid_item(item_node_id):
            return False, "Invalid item node id."

        producers, _consumers = self._build_adjacency()
        if len(producers[item_node_id]) > 0:
            return False, "This node is already produced. Expand a different node."

        item_node = self.item_nodes[item_node_id]
        item_name = item_node.name

        out_pos = [i for i, (out, _rate) in enumerate(recipe.outs) if item_name == out]
        if len(out_pos) == 0:
            return False, "Selected recipe does not produce this item."
        if len(out_pos) > 1:
            return False, "Recipe has duplicated outputs for this item; cannot disambiguate."
        out_pos = out_pos[0]

        out_rate = recipe.outs[out_pos][1]
        if out_rate <= 0:
            return False, "Invalid recipe output rate."

        machines = item_node.rate / out_rate
        if machines <= 0:
            return False, "Target node rate must be positive."

        recipe_outs = []
        for i, (new_item_name, rate) in enumerate(recipe.outs):
            if i == out_pos:
                recipe_outs.append(item_node_id)
                continue
            new_item_id = len(self.item_nodes)
            self.item_nodes.append(ItemNode(name=new_item_name, rate=machines * rate))
            recipe_outs.append(new_item_id)

        recipe_ins = []
        for new_item_name, rate in recipe.ins:
            new_item_id = len(self.item_nodes)
            self.item_nodes.append(ItemNode(name=new_item_name, rate=machines * rate))
            recipe_ins.append(new_item_id)

        self.recipe_nodes.append(
            RecipeNode(
                recipe=recipe,
                machines=machines,
                machine_name=recipe.machine_name,
                in_ids=recipe_ins,
                out_ids=recipe_outs,
            )
        )

        return True, "Expanded."

    def scale_connected_component(self, item_node_id: int, target_rate: float) -> tuple[bool, str]:
        if not self._is_valid_item(item_node_id):
            return False, "Invalid item node id."
        if target_rate <= 0:
            return False, "Target rate must be positive."

        current_rate = self.item_nodes[item_node_id].rate
        if current_rate <= 0:
            return False, "Current node rate is zero; cannot scale by ratio."

        factor = target_rate / current_rate

        producers, consumers = self._build_adjacency()
        visited_items = set([item_node_id])
        visited_recipes = set()
        queue = deque([("item", item_node_id)])

        while queue:
            node_type, node_id = queue.popleft()
            if node_type == "item":
                for recipe_id in producers[node_id]:
                    if recipe_id not in visited_recipes:
                        visited_recipes.add(recipe_id)
                        queue.append(("recipe", recipe_id))
                for recipe_id in consumers[node_id]:
                    if recipe_id not in visited_recipes:
                        visited_recipes.add(recipe_id)
                        queue.append(("recipe", recipe_id))
            else:
                recipe_node = self.recipe_nodes[node_id]
                if not recipe_node.active:
                    continue
                for item_id in recipe_node.in_ids + recipe_node.out_ids:
                    if self._is_valid_item(item_id) and item_id not in visited_items:
                        visited_items.add(item_id)
                        queue.append(("item", item_id))

        for recipe_id in visited_recipes:
            self.recipe_nodes[recipe_id].machines *= factor
        for item_id in visited_items:
            self.item_nodes[item_id].rate *= factor

        return True, (
            f"Scaled component by x{factor:.5f} "
            f"({len(visited_items)} item nodes, {len(visited_recipes)} recipe nodes)."
        )

    def merge_leaves(self, item_node_ids: list[int]) -> tuple[bool, str]:
        ordered_unique_ids = []
        seen = set()
        for item_id in item_node_ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            ordered_unique_ids.append(item_id)

        if len(ordered_unique_ids) < 2:
            return False, "Specify at least two distinct item node IDs."
        for item_id in ordered_unique_ids:
            if not self._is_valid_item(item_id):
                return False, f"Invalid item node id: {item_id}"

        names = {self.item_nodes[item_id].name for item_id in ordered_unique_ids}
        if len(names) != 1:
            return False, "Only same-name item nodes can be merged."

        producers, consumers = self._build_adjacency()
        for item_id in ordered_unique_ids:
            if len(producers[item_id]) > 0:
                return False, f"Item node {item_id} is not a leaf (already has producer)."
            if len(consumers[item_id]) == 0:
                return False, f"Item node {item_id} has no consumers."

        keep_id = ordered_unique_ids[0]
        drop_set = set(ordered_unique_ids[1:])
        merged_rate = sum(self.item_nodes[item_id].rate for item_id in ordered_unique_ids)

        for recipe_node in self.recipe_nodes:
            if not recipe_node.active:
                continue
            recipe_node.in_ids = [keep_id if in_id in drop_set else in_id for in_id in recipe_node.in_ids]

        self.item_nodes[keep_id].rate = merged_rate
        for item_id in ordered_unique_ids[1:]:
            self.item_nodes[item_id].active = False

        return True, f"Merged into node {keep_id} ({self.item_nodes[keep_id].name} {merged_rate:.5f}/min)."

    def total_power_mw(self, power_model: PowerModel) -> float:
        total = 0.0
        for recipe_node in self.recipe_nodes:
            if not recipe_node.active:
                continue
            per_machine = power_model.power_per_machine_mw(recipe_node.recipe)
            total += per_machine * recipe_node.machines
        return total

    def _top_item_lines(self) -> list[str]:
        _producers, consumers = self._build_adjacency()
        top_items = []
        for item_id, item_node in enumerate(self.item_nodes):
            if not item_node.active:
                continue
            if len(consumers[item_id]) == 0:
                top_items.append((item_id, item_node.name, item_node.rate))
        if len(top_items) == 0:
            return []
        top_items.sort(key=lambda x: x[0])
        _, name, rate = top_items[0]
        return [f"{name} {rate:.3f}/min"]

    def to_viz(self, power_model: PowerModel | None = None):
        os.makedirs("output", exist_ok=True)
        dot = graphviz.Digraph("plan")
        dot.graph_attr["rankdir"] = "BT"
        if power_model is not None:
            total_power = self.total_power_mw(power_model)
            title_lines = self._top_item_lines()
            label = f"{total_power:.3f} MW"
            if len(title_lines) > 0:
                label = "\\n".join(title_lines + [label])
            dot.graph_attr["labelloc"] = "t"
            dot.graph_attr["label"] = label

        for item_id, item_node in enumerate(self.item_nodes):
            if not item_node.active:
                continue
            dot.node(f"I{item_id}", item_node.label(item_id), shape="circle")
        for recipe_id, recipe_node in enumerate(self.recipe_nodes):
            if not recipe_node.active:
                continue
            dot.node(f"R{recipe_id}", recipe_node.label(), shape="box")

        for recipe_id, recipe_node in enumerate(self.recipe_nodes):
            if not recipe_node.active:
                continue
            for in_id in recipe_node.in_ids:
                if self._is_valid_item(in_id):
                    dot.edge(f"I{in_id}", f"R{recipe_id}")
            for out_id in recipe_node.out_ids:
                if self._is_valid_item(out_id):
                    dot.edge(f"R{recipe_id}", f"I{out_id}")

        dot.render(directory="output")


@dataclass
class SessionState:
    graph: GenGraph
    label: str


def load_recipe_sfplus():
    with open("DB.csv") as f:
        reader = csv.reader(f)
        next(reader)  # header
        next(reader)

        recipes = []
        for row in reader:
            ins = [(name.strip(), float(rate)) for name, rate in zip(row[0:8:2], row[1:9:2]) if name.strip() != ""]
            outs = [(name.strip(), float(rate)) for name, rate in zip(row[8::2], row[9::2]) if name.strip() != "" and rate != ""]
            if len(ins) == 0:
                continue
            recipes.append(Recipe(ins=ins, outs=outs))
        return recipes


def load_recipe_vanilla1_0():
    with open("DB_stable.json", "r") as f:
        d = json.load(f)

    def is_valid_cname(cname):
        return cname.startswith("/Game/FactoryGame/Resource/Parts/") or cname.startswith("/Game/FactoryGame/Resource/RawResources")

    cname_to_name = defaultdict(str)
    for val in d["itemsData"].values():
        if is_valid_cname(val["className"]):
            cname_to_name[val["className"]] = val["name"]

    power_used_by_machine_class: dict[str, float] = {}
    power_used_recipes_by_machine_class: dict[str, dict[str, tuple[float, float]]] = {}
    for b in d["buildingsData"].values():
        machine_class = b.get("className")
        if not machine_class:
            continue
        power_used = b.get("powerUsed")
        if isinstance(power_used, (int, float)):
            power_used_by_machine_class[machine_class] = float(power_used)
        if isinstance(b.get("powerUsedRecipes"), dict):
            parsed = {}
            for recipe_id, bounds in b["powerUsedRecipes"].items():
                if (
                    isinstance(bounds, (list, tuple))
                    and len(bounds) == 2
                    and isinstance(bounds[0], (int, float))
                    and isinstance(bounds[1], (int, float))
                ):
                    parsed[recipe_id] = (float(bounds[0]), float(bounds[1]))
            if len(parsed) > 0:
                power_used_recipes_by_machine_class[machine_class] = parsed

    recipes = []

    def add_item(recipe_id: str, item):
        t = float(item["mManufactoringDuration"])
        if "mProducedIn" not in item:
            return
        for ing in item["ingredients"]:
            if not is_valid_cname(ing):
                return
        for ing in item["produce"]:
            if not is_valid_cname(ing):
                return

        ins = [(cname_to_name[ing], 60 / t * amount) for ing, amount in item["ingredients"].items()]
        outs = [(cname_to_name[ing], 60 / t * amount) for ing, amount in item["produce"].items()]

        machine_name = "Machine"
        machine_class = ""
        for cand in item["mProducedIn"]:
            try:
                machine_name = cand.split("_")[-2].removesuffix("Mk1")
                machine_class = cand
                break
            except Exception:
                continue
        recipes.append(
            Recipe(
                ins=ins,
                outs=outs,
                machine_name=machine_name,
                machine_class=machine_class,
                recipe_id=recipe_id,
            )
        )

    for recipe_id, item in d["recipesData"].items():
        if not item["name"].startswith("Alternate:"):
            add_item(recipe_id, item)
    for recipe_id, item in d["recipesData"].items():
        if item["name"].startswith("Alternate:"):
            add_item(recipe_id, item)

    return recipes, PowerModel(
        power_used_by_machine_class=power_used_by_machine_class,
        power_used_recipes_by_machine_class=power_used_recipes_by_machine_class,
    )


def color_text(text: str, color: str) -> str:
    if Fore is None or Style is None:
        return text
    return f"{color}{text}{Style.RESET_ALL}"


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


def _latest_session_path() -> str | None:
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


def _list_session_paths() -> list[str]:
    if not os.path.isdir("sessions"):
        return []
    cands = [
        os.path.join("sessions", name)
        for name in os.listdir("sessions")
        if name.endswith(".json")
    ]
    cands.sort(key=os.path.getmtime, reverse=True)
    return cands


def _resolve_session_path(raw: str) -> str | None:
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


def print_help():
    print("Commands:")
    print("  <node_id>                 Expand an item node by choosing recipe")
    print("  scale <node_id> <rate>    Set the node's rate (/min) and scale its connected component")
    print("  merge <id1> <id2> ...     Merge same-name leaf nodes into one")
    print("  resume -l                 List saved sessions")
    print("  resume [filename]         Load latest session or specified file")
    print("  undo                       Undo the previous mutating command")
    print("  nodes                      Print active item nodes")
    print("  help                       Show this help")
    print("  quit                       Exit")


def main():
    colorama_init(autoreset=True)
    command_prompt = color_text("command> ", Fore.CYAN if Fore else "")
    recipe_prompt = color_text("recipe> ", Fore.YELLOW if Fore else "")

    recipes, power_model = load_recipe_vanilla1_0()

    item_to_recipe = defaultdict(list)
    for recipe in recipes:
        for out, _rate in recipe.outs:
            item_to_recipe[out].append(recipe)

    argv = sys.argv[1:]
    if len(argv) % 2 != 0:
        print("Usage: python run.py [output1] [output1-rate] [output2] [output2-rate] ...")
        sys.exit(1)

    gen_graph = GenGraph(item_nodes=[], recipe_nodes=[])
    initial_pairs: list[tuple[str, float]] = []
    for output_name, rate in zip(argv[::2], argv[1::2]):
        parsed_rate = float(rate)
        gen_graph.item_nodes.append(ItemNode(output_name, parsed_rate))
        initial_pairs.append((output_name, parsed_rate))
    session_label = build_session_label(initial_pairs) if len(initial_pairs) > 0 else "empty"

    history: list[SessionState] = []
    print_help()
    if len(initial_pairs) == 0:
        print("No target item specified. Use 'resume' to load a previous session.")

    try:
        while True:
            gen_graph.to_viz(power_model)
            command = input(command_prompt).strip()
            if command == "":
                continue

            tokens = command.split()
            try:
                if tokens[0] in {"quit", "q", "exit"}:
                    break

                if tokens[0] in {"help", "h", "?"}:
                    print_help()
                    continue

                if tokens[0] == "nodes":
                    for line in gen_graph.list_active_items():
                        print(line)
                    continue

                if tokens[0] == "undo":
                    if len(history) == 0:
                        print("Nothing to undo.")
                    else:
                        prev = history.pop()
                        gen_graph = prev.graph
                        session_label = prev.label
                        print("Undone.")
                    continue

                if tokens[0] == "resume":
                    if len(tokens) > 2:
                        print("Usage: resume [-l] [filename]")
                        continue
                    if len(tokens) == 2 and tokens[1] in {"-l", "--list"}:
                        paths = _list_session_paths()
                        if len(paths) == 0:
                            print("No session files found under sessions/.")
                            continue
                        print("Saved sessions (latest first):")
                        for path in paths:
                            print(f"  {os.path.basename(path)}")
                        continue
                    if len(tokens) == 1:
                        path = _latest_session_path()
                        if path is None:
                            print("No session files found under sessions/.")
                            continue
                    else:
                        path = _resolve_session_path(tokens[1])
                        if path is None:
                            print("Session file not found.")
                            continue

                    state = load_session(path)
                    history.append(SessionState(graph=copy.deepcopy(gen_graph), label=session_label))
                    gen_graph = state.graph
                    session_label = state.label
                    print(f"Loaded session: {path}")
                    continue

                if tokens[0] == "scale":
                    if len(tokens) != 3:
                        print("Usage: scale <node_id> <rate>")
                        continue
                    item_node_id = int(tokens[1])
                    target_rate = float(tokens[2])
                    history.append(SessionState(graph=copy.deepcopy(gen_graph), label=session_label))
                    ok, msg = gen_graph.scale_connected_component(item_node_id, target_rate)
                    if not ok:
                        history.pop()
                    print(msg)
                    continue

                if tokens[0] == "merge":
                    if len(tokens) < 3:
                        print("Usage: merge <id1> <id2> ...")
                        continue
                    item_node_ids = [int(x) for x in tokens[1:]]
                    history.append(SessionState(graph=copy.deepcopy(gen_graph), label=session_label))
                    ok, msg = gen_graph.merge_leaves(item_node_ids)
                    if not ok:
                        history.pop()
                    print(msg)
                    continue

                if len(tokens) != 1:
                    print("Invalid command.")
                    continue

                item_node_id = int(tokens[0])
                if not gen_graph._is_valid_item(item_node_id):
                    print("Invalid node id.")
                    continue

                item_node = gen_graph.item_nodes[item_node_id]
                cands = item_to_recipe[item_node.name]
                if len(cands) == 0:
                    print("Cannot expand: no recipes.")
                    continue

                if len(cands) == 1:
                    history.append(SessionState(graph=copy.deepcopy(gen_graph), label=session_label))
                    ok, msg = gen_graph.expand(item_node_id, cands[0])
                    if not ok:
                        history.pop()
                    print(msg)
                    continue

                print(color_text("Choose recipe (blank/cancel to abort):", Fore.YELLOW if Fore else ""))
                for i, cand in enumerate(cands):
                    print(color_text(f"[{i}] {cand.str()}", Fore.YELLOW if Fore else ""))
                choice = input(recipe_prompt).strip()
                if choice in {"", "cancel", "c"}:
                    continue
                recipe_index = int(choice)
                if not (0 <= recipe_index < len(cands)):
                    print("Invalid recipe id.")
                    continue

                history.append(SessionState(graph=copy.deepcopy(gen_graph), label=session_label))
                ok, msg = gen_graph.expand(item_node_id, cands[recipe_index])
                if not ok:
                    history.pop()
                print(msg)
            except ValueError:
                print("Invalid numeric value.")
            except Exception:
                print("Invalid command.")
    except (KeyboardInterrupt, EOFError):
        print()
        print("Interrupted.")
    finally:
        save_label = session_label or infer_label_from_graph(gen_graph)
        save_path = save_session(SessionState(graph=gen_graph, label=save_label))
        print(f"Session saved: {save_path}")


if __name__ == "__main__":
    main()
