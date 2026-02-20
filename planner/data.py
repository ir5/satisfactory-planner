import csv
import json
from collections import defaultdict

from planner.models import Recipe
from planner.power import PowerModel


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

