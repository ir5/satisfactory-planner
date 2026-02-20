import os
from collections import defaultdict, deque
from dataclasses import dataclass

import graphviz

from planner.models import ItemNode, Recipe, RecipeNode
from planner.power import PowerModel


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

