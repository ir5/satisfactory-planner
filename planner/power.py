from dataclasses import dataclass

from planner.models import Recipe


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

