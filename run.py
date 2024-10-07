import graphviz
import csv
from dataclasses import dataclass
from collections import defaultdict
from typing import Optional
import json


@dataclass
class Recipe:
    ins: list[tuple[str, float]]
    outs: list[tuple[str, float]]
    machine_name: str

    def str(self):
        instr = " ".join(f"{name} {rate:.2f}/min" for name, rate in self.ins)
        outstr = " ".join(f"{name} {rate:.2f}/min" for name, rate in self.outs)
        return f"{instr} ==> {outstr}"


@dataclass
class ItemNode:
    name: str
    rate: float
    parent_recipe_id: Optional[int]
    comsumer_recipe_id: Optional[int]

    def label(self, node_id):
        return f"[{node_id}]\n{self.rate:.5f}/min\n{self.name}"


@dataclass
class RecipeNode:
    recipe: Recipe
    machines: float
    machine_name: str
    in_ids: list[int]
    out_ids: list[int]

    def label(self):
        return f"{self.machine_name}\nx{self.machines:.9f}"


@dataclass
class GenGraph:
    item_nodes: list[ItemNode]
    recipe_nodes: list[RecipeNode]

    def expand(self, item_node_id: int, recipe: Recipe) -> bool:
        item_node = self.item_nodes[item_node_id]
        item_name = item_node.name

        out_pos = [i for i, (out, _rate) in enumerate(recipe.outs) if item_name == out]
        if len(out_pos) == 0:
            return False
        assert len(out_pos) == 1
        out_pos = out_pos[0]

        machines = item_node.rate / recipe.outs[out_pos][1]

        # add nodes
        recipe_node_id = len(self.recipe_nodes)
        recipe_outs = []

        # byproducts
        for new_item_name, rate in recipe.outs:
            if new_item_name == item_name:
                recipe_outs.append(item_node_id)
                continue
            new_rate = rate=machines * rate
            new_item = ItemNode(name=new_item_name,
                                rate=new_rate,
                                parent_recipe_id=recipe_node_id,
                                comsumer_recipe_id=None)
            new_item_id = len(self.item_nodes)
            self.item_nodes.append(new_item)
            recipe_outs.append(new_item_id)

        # new required items
        recipe_ins = []
        for new_item_name, rate in recipe.ins:
            new_rate = rate=machines * rate
            new_item = ItemNode(name=new_item_name,
                                rate=new_rate,
                                parent_recipe_id=None,
                                comsumer_recipe_id=recipe_node_id)
            new_item_id = len(self.item_nodes)
            self.item_nodes.append(new_item)
            recipe_ins.append(new_item_id)

        recipe_node = RecipeNode(
            recipe=recipe,
            machines=machines,
            machine_name=recipe.machine_name,
            in_ids=recipe_ins,
            out_ids=recipe_outs
        )
        self.recipe_nodes.append(recipe_node)

        return True

    def scale(self, factor: float):
        assert factor > 0

        for recipe_node in self.recipe_nodes:
            recipe_node.machines *= factor
        for item_node in self.item_nodes:
            item_node.rate *= factor

    def to_viz(self):
        dot = graphviz.Digraph("plan")
        dot.graph_attr["rankdir"] = "BT"

        for i, item_node in enumerate(self.item_nodes):
            dot.node(f"I{i}", item_node.label(i), shape="circle")
        for i, recipe_node in enumerate(self.recipe_nodes):
            dot.node(f"R{i}", recipe_node.label(), shape="box")

        for i, recipe_node in enumerate(self.recipe_nodes):
            for in_id in recipe_node.in_ids:
                dot.edge(f"I{in_id}", f"R{i}")
            for out_id in recipe_node.out_ids:
                dot.edge(f"R{i}", f"I{out_id}")

        dot.render(directory="output")


def load_reicpe_sfplus():
    with open("DB.csv") as f:
        reader = csv.reader(f)

        next(reader)  # skip header
        next(reader)

        recipes = []
        for row in reader:
            ins = [(name.strip(), float(rate)) for name, rate in zip(row[0:8:2], row[1:9:2]) if name.strip() != ""]
            outs = [(name.strip(), float(rate)) for name, rate in zip(row[8::2], row[9::2]) if name.strip() != "" and rate != ""]

            if len(ins) == 0:
                continue

            recipe = Recipe(ins, outs)
            recipes.append(recipe)


def load_recipe_vanilla():
    with open("DB_vanilla.json", "r") as f:
        d = json.load(f)

    cname_to_name = {}
    for key, val in d["items"].items():
        if key.startswith("Desc_"):
            cname_to_name[val["className"]] = val["name"]

    recipes = []

    def add_item(item):
        t = float(item["time"])
        if not item["inMachine"]:
            return

        ok = True
        for ing in item["ingredients"]:
            if not ing["item"].startswith("Desc_"):
                ok = False
        for ing in item["products"]:
            if not ing["item"].startswith("Desc_"):
                ok = False
        if not ok:
            return

        ins = [
            (cname_to_name[ing["item"]], 60 / t * ing["amount"])
            for ing in item["ingredients"]
        ]
        outs = [
            (cname_to_name[ing["item"]], 60 / t * ing["amount"])
            for ing in item["products"]
        ]
        recipe = Recipe(ins, outs)
        recipes.append(recipe)

    for item in d["recipes"].values():
        if not item["alternate"]:
            add_item(item)
    for item in d["recipes"].values():
        if item["alternate"]:
            add_item(item)

    return recipes


def load_recipe_vanilla1_0():
    with open("DB_stable.json", "r") as f:
        d = json.load(f)

    def is_valid_cname(cname):
        return cname.startswith("/Game/FactoryGame/Resource/Parts/") or\
            cname.startswith("/Game/FactoryGame/Resource/RawResources")

    cname_to_name = defaultdict(str)
    for val in d["itemsData"].values():
        if is_valid_cname(val["className"]):
            cname_to_name[val["className"]] = val["name"]

    recipes = []

    def add_item(item):
        t = float(item["mManufactoringDuration"])
        if "mProducedIn" not in item:
            return

        for ing in item["ingredients"]:
            if not is_valid_cname(ing):
                return
        for ing in item["produce"]:
            if not is_valid_cname(ing):
                return

        ins = [
            (cname_to_name[ing], 60 / t * amount)
            for ing, amount in item["ingredients"].items()
        ]
        outs = [
            (cname_to_name[ing], 60 / t * amount)
            for ing, amount in item["produce"].items()
        ]

        machine_name = ""
        for cand in item["mProducedIn"]:
            try:
                machine_name = cand.split("_")[-2].removesuffix("Mk1")
            except Exception:
                continue

        recipe = Recipe(ins, outs, machine_name)
        recipes.append(recipe)

    for item in d["recipesData"].values():
        if not item["name"].startswith("Alternate:"):
            add_item(item)
    for item in d["recipesData"].values():
        if item["name"].startswith("Alternate:"):
            add_item(item)

    return recipes


def main():
    # recipes = load_recipe_vanilla()
    recipes = load_recipe_vanilla1_0()

    item_to_recipe: dict[str, list[Recipe]] = {}

    for recipe in recipes:
        for out, _rate in recipe.outs:
            if out not in item_to_recipe:
                item_to_recipe[out] = []
            item_to_recipe[out].append(recipe)

    import sys
    # load objective
    argv = sys.argv[1:]
    if len(argv) == 0 or len(argv) % 2 != 0:
        print("Usage: python run.py [output1] [output1-rate] [output2] [output2-rate] ...")
        sys.exit(1)

    gen_graph = GenGraph([], [])

    for output_name, rate in zip(argv[::2], argv[1::2]):
        item_node = ItemNode(output_name, float(rate), None, None)
        gen_graph.item_nodes.append(item_node)

    while True:
        gen_graph.to_viz()

        print("Choose expand node:")
        command = input()

        try:
            tokens = command.rstrip().split()

            if len(tokens) == 2:
                if tokens[0] == "scale":
                    factor = float(tokens[1])
                    print("scaling factor:", factor)
                    gen_graph.scale(factor)
                continue
            elif len(tokens) > 2:
                continue

            item_node_id = int(command)
            item_node = gen_graph.item_nodes[item_node_id]

            if item_node.name not in item_to_recipe:
                print("Cannot expand!")
                continue

            cands = item_to_recipe[item_node.name]
            if len(cands) == 1:
                gen_graph.expand(item_node_id, cands[0])
                continue

            print("Choose recipe:")
            for i, cand in enumerate(cands):
                print(f"[{i}]: {cand.str()}")

            command = input()
            i = int(command)
            gen_graph.expand(item_node_id, cands[i])
        except Exception:
            print("Invalid!")


if __name__ == "__main__":
    main()
