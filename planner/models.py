from dataclasses import dataclass


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


@dataclass
class SessionState:
    graph: "GenGraph"
    label: str

