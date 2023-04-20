import graphviz
import csv
from dataclasses import dataclass
from typing import Optional


@dataclass
class Recipe:
    ins: list[tuple[str, float]]
    outs: list[tuple[str, float]]

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
        return f"[{node_id}]\n{self.rate:.1f}/min\n{self.name}"


@dataclass
class RecipeNode:
    recipe: Recipe
    machines: float
    in_ids: list[int]
    out_ids: list[int]

    def label(self):
        return f"x{self.machines:.2f}"


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

        recipe_node = RecipeNode(recipe=recipe, machines=machines, in_ids=recipe_ins, out_ids=recipe_outs)
        self.recipe_nodes.append(recipe_node)

        return True

    def to_viz(self):
        dot = graphviz.Digraph("plan")

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



def main():
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
