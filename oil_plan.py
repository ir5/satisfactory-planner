import argparse
import os
from dataclasses import dataclass

import graphviz

REFINERY_POWER_MW = 30.0
BLENDER_POWER_MW = 75.0
PACKAGER_POWER_MW = 10.0


@dataclass
class OilPlanSingle:
    mode: str
    product: str
    target_rate: float
    use_packaged_dilution: bool
    crude_oil: float
    water: float
    heavy_oil_residue: float
    fuel: float
    m_base_rubber: float
    m_blender_diluted_fuel: float
    m_packaged_dilution_refinery: float
    m_packaged_water_packager: float
    m_unpackaged_fuel_packager: float
    m_recycled_plastic_1: float
    m_recycled_rubber_1: float
    m_recycled_plastic_2: float
    out_from_rubber_path: float
    out_from_plastic_path: float
    note: str


def fmt(value: float) -> str:
    return f"{value:.3f}/min"


def item_label(name: str, rate: float) -> str:
    return f"{name}\n{rate:.5f}/min"


def recipe_label(machine_name: str, machines: float) -> str:
    return f"{machine_name}\nx{machines:.10f}"


def total_power_mw(plan: OilPlanSingle) -> float:
    refinery_machines = (
        plan.m_base_rubber
        + plan.m_packaged_dilution_refinery
        + plan.m_recycled_plastic_1
        + plan.m_recycled_rubber_1
        + plan.m_recycled_plastic_2
    )
    return (
        REFINERY_POWER_MW * refinery_machines
        + BLENDER_POWER_MW * plan.m_blender_diluted_fuel
        + PACKAGER_POWER_MW * (plan.m_packaged_water_packager + plan.m_unpackaged_fuel_packager)
    )


def build_2x_rubber_plan(rate: float, use_packaged_dilution: bool) -> OilPlanSingle:
    if rate <= 0:
        raise ValueError("rate must be positive.")

    # Feed-forward no-loop:
    # Base Rubber -> RP1 -> RR1 -> Rubber output (+ base split output)
    b = rate / 60.0
    m_base = b
    m_blender_dilute = 0.4 * b
    m_packaged_dilution_refinery = 2.0 / 3.0 * b if use_packaged_dilution else 0.0
    m_packaged_water_packager = 2.0 / 3.0 * b if use_packaged_dilution else 0.0
    m_unpackaged_fuel_packager = 2.0 / 3.0 * b if use_packaged_dilution else 0.0
    m_rp1 = 4.0 / 9.0 * b
    m_rr1 = 8.0 / 9.0 * b

    crude = 30000.0 * b
    hor = 20000.0 * b
    # Both blender and packaged dilution routes have the same net ratio:
    # 1 HOR + 2 Water -> 2 Fuel
    water = 40000.0 * b
    fuel = 40000.0 * b

    out_from_base_split = 20.0 * b - 30.0 * m_rp1
    out_from_rr = 60.0 * m_rr1
    # total = out_from_base_split + out_from_rr == rate

    return OilPlanSingle(
        mode="2.0",
        product="Rubber",
        target_rate=rate,
        use_packaged_dilution=use_packaged_dilution,
        crude_oil=crude,
        water=water,
        heavy_oil_residue=hor,
        fuel=fuel,
        m_base_rubber=m_base,
        m_blender_diluted_fuel=m_blender_dilute if not use_packaged_dilution else 0.0,
        m_packaged_dilution_refinery=m_packaged_dilution_refinery,
        m_packaged_water_packager=m_packaged_water_packager,
        m_unpackaged_fuel_packager=m_unpackaged_fuel_packager,
        m_recycled_plastic_1=m_rp1,
        m_recycled_rubber_1=m_rr1,
        m_recycled_plastic_2=0.0,
        out_from_rubber_path=out_from_base_split,
        out_from_plastic_path=out_from_rr,
        note=(
            "2-stage feed-forward (no closed loop, packaged dilution)"
            if use_packaged_dilution
            else "2-stage feed-forward (no closed loop)"
        ),
    )


def build_2x_plastic_plan(rate: float, use_packaged_dilution: bool) -> OilPlanSingle:
    if rate <= 0:
        raise ValueError("rate must be positive.")

    # Feed-forward no-loop:
    # Base Rubber -> RP1 -> RR1 -> RP2 -> Plastic output (+ RP1 split output)
    b = rate / 60.0
    m_base = b
    m_blender_dilute = 0.4 * b
    m_packaged_dilution_refinery = 2.0 / 3.0 * b if use_packaged_dilution else 0.0
    m_packaged_water_packager = 2.0 / 3.0 * b if use_packaged_dilution else 0.0
    m_unpackaged_fuel_packager = 2.0 / 3.0 * b if use_packaged_dilution else 0.0
    m_rp1 = 2.0 / 3.0 * b
    m_rr1 = 2.0 / 9.0 * b
    m_rp2 = 4.0 / 9.0 * b

    crude = 30000.0 * b
    hor = 20000.0 * b
    water = 40000.0 * b
    fuel = 40000.0 * b

    out_from_rp1_split = 60.0 * m_rp1 - 30.0 * m_rr1
    out_from_rp2 = 60.0 * m_rp2
    # total = out_from_rp1_split + out_from_rp2 == rate

    return OilPlanSingle(
        mode="2.0",
        product="Plastic",
        target_rate=rate,
        use_packaged_dilution=use_packaged_dilution,
        crude_oil=crude,
        water=water,
        heavy_oil_residue=hor,
        fuel=fuel,
        m_base_rubber=m_base,
        m_blender_diluted_fuel=m_blender_dilute if not use_packaged_dilution else 0.0,
        m_packaged_dilution_refinery=m_packaged_dilution_refinery,
        m_packaged_water_packager=m_packaged_water_packager,
        m_unpackaged_fuel_packager=m_unpackaged_fuel_packager,
        m_recycled_plastic_1=m_rp1,
        m_recycled_rubber_1=m_rr1,
        m_recycled_plastic_2=m_rp2,
        out_from_rubber_path=out_from_rp1_split,
        out_from_plastic_path=out_from_rp2,
        note=(
            "3-stage feed-forward (no closed loop, packaged dilution)"
            if use_packaged_dilution
            else "3-stage feed-forward (no closed loop)"
        ),
    )


def build_2x_plan(product: str, rate: float, use_packaged_dilution: bool) -> OilPlanSingle:
    p = product.strip().lower()
    if p == "rubber":
        return build_2x_rubber_plan(rate, use_packaged_dilution)
    if p == "plastic":
        return build_2x_plastic_plan(rate, use_packaged_dilution)
    raise ValueError("product must be Rubber or Plastic.")


def build_13_rubber_plan(rate: float, use_packaged_dilution: bool) -> OilPlanSingle:
    if rate <= 0:
        raise ValueError("rate must be positive.")

    # Feed-forward no-loop, no byproducts:
    # Base Plastic -> RR1 -> Rubber output
    #
    # Base Plastic output: 20b, HOR: 10000b, Fuel from dilution: 20000b
    # RR1 consumes Plastic 30y and Fuel 30000y, outputs Rubber 60y
    # For no byproducts: 30y=20b and 30000y=20000b => y=2b/3
    # Target Rubber = 60y = 40b => b = rate/40
    b = rate / 40.0
    m_base = b

    if use_packaged_dilution:
        m_blender_dilute = 0.0
        m_packaged_dilution_refinery = b / 3.0
        m_packaged_water_packager = b / 3.0
        m_unpackaged_fuel_packager = b / 3.0
    else:
        m_blender_dilute = 0.2 * b
        m_packaged_dilution_refinery = 0.0
        m_packaged_water_packager = 0.0
        m_unpackaged_fuel_packager = 0.0

    m_rr1 = 2.0 * b / 3.0

    crude = 30000.0 * b
    hor = 10000.0 * b
    water = 20000.0 * b
    fuel = 20000.0 * b

    return OilPlanSingle(
        mode="1.3",
        product="Rubber",
        target_rate=rate,
        use_packaged_dilution=use_packaged_dilution,
        crude_oil=crude,
        water=water,
        heavy_oil_residue=hor,
        fuel=fuel,
        m_base_rubber=m_base,
        m_blender_diluted_fuel=m_blender_dilute,
        m_packaged_dilution_refinery=m_packaged_dilution_refinery,
        m_packaged_water_packager=m_packaged_water_packager,
        m_unpackaged_fuel_packager=m_unpackaged_fuel_packager,
        m_recycled_plastic_1=0.0,
        m_recycled_rubber_1=m_rr1,
        m_recycled_plastic_2=0.0,
        out_from_rubber_path=0.0,
        out_from_plastic_path=rate,
        note=(
            "1.3 feed-forward (no closed loop, no byproducts, packaged dilution)"
            if use_packaged_dilution
            else "1.3 feed-forward (no closed loop, no byproducts)"
        ),
    )


def build_13_plastic_plan(rate: float, use_packaged_dilution: bool) -> OilPlanSingle:
    if rate <= 0:
        raise ValueError("rate must be positive.")

    # Feed-forward no-loop, no byproducts:
    # Base Plastic -> RR1 -> RP2 -> Plastic output (+ direct Plastic output from base)
    #
    # Let base count b:
    # Base Plastic 20b, Fuel 20000b (from HOR 10000b)
    # RR1 count y, RP2 count z
    # No byproducts:
    #  - all Rubber from RR1 consumed by RP2: 60y = 30z -> z = 2y
    #  - all Fuel consumed: 30000y + 30000z = 20000b -> y = 2b/9, z = 4b/9
    # Output Plastic = (20b - 30y) + 60z = 40b => b = rate/40
    b = rate / 40.0
    m_base = b

    if use_packaged_dilution:
        m_blender_dilute = 0.0
        m_packaged_dilution_refinery = b / 3.0
        m_packaged_water_packager = b / 3.0
        m_unpackaged_fuel_packager = b / 3.0
    else:
        m_blender_dilute = 0.2 * b
        m_packaged_dilution_refinery = 0.0
        m_packaged_water_packager = 0.0
        m_unpackaged_fuel_packager = 0.0

    m_rr1 = 2.0 * b / 9.0
    m_rp2 = 4.0 * b / 9.0

    crude = 30000.0 * b
    hor = 10000.0 * b
    water = 20000.0 * b
    fuel = 20000.0 * b

    direct_plastic = 20.0 * b - 30.0 * m_rr1
    plastic_from_rp2 = 60.0 * m_rp2

    return OilPlanSingle(
        mode="1.3",
        product="Plastic",
        target_rate=rate,
        use_packaged_dilution=use_packaged_dilution,
        crude_oil=crude,
        water=water,
        heavy_oil_residue=hor,
        fuel=fuel,
        m_base_rubber=m_base,
        m_blender_diluted_fuel=m_blender_dilute,
        m_packaged_dilution_refinery=m_packaged_dilution_refinery,
        m_packaged_water_packager=m_packaged_water_packager,
        m_unpackaged_fuel_packager=m_unpackaged_fuel_packager,
        m_recycled_plastic_1=0.0,
        m_recycled_rubber_1=m_rr1,
        m_recycled_plastic_2=m_rp2,
        out_from_rubber_path=direct_plastic,
        out_from_plastic_path=plastic_from_rp2,
        note=(
            "1.3 feed-forward (no closed loop, no byproducts, packaged dilution)"
            if use_packaged_dilution
            else "1.3 feed-forward (no closed loop, no byproducts)"
        ),
    )


def build_plan(mode: str, product: str, rate: float, use_packaged_dilution: bool) -> OilPlanSingle:
    if mode == "2.0":
        return build_2x_plan(product, rate, use_packaged_dilution)
    if mode == "1.3":
        p = product.strip().lower()
        if p == "rubber":
            return build_13_rubber_plan(rate, use_packaged_dilution)
        if p == "plastic":
            return build_13_plastic_plan(rate, use_packaged_dilution)
    raise ValueError("Unsupported mode/product combination.")


def render_2x_plan(plan: OilPlanSingle, out_base: str):
    out_dir = os.path.dirname(out_base) or "."
    out_name = os.path.basename(out_base)
    os.makedirs(out_dir, exist_ok=True)

    dot = graphviz.Digraph("oil_plan")
    dot.graph_attr["rankdir"] = "BT"
    dot.graph_attr["labelloc"] = "t"
    power = total_power_mw(plan)
    dot.graph_attr["label"] = f"{plan.product} {plan.target_rate:.3f}/min\\n{power:.3f} MW"

    dot.node("N_CRUDE", item_label("Crude Oil", plan.crude_oil), shape="circle")
    dot.node("N_WATER", item_label("Water", plan.water), shape="circle")
    dot.node("N_HOR", item_label("Heavy Oil Residue", plan.heavy_oil_residue), shape="circle")
    dot.node("N_FUEL", item_label("Fuel", plan.fuel), shape="circle")

    if plan.mode == "2.0":
        dot.node("N_R0", item_label("Rubber", 20.0 * plan.m_base_rubber), shape="circle")
        dot.node("N_P1", item_label("Plastic", 60.0 * plan.m_recycled_plastic_1), shape="circle")
        dot.node("N_R1", item_label("Rubber", 60.0 * plan.m_recycled_rubber_1), shape="circle")
    else:
        dot.node("N_P0", item_label("Plastic", 20.0 * plan.m_base_rubber), shape="circle")
        dot.node("N_R1", item_label("Rubber", 60.0 * plan.m_recycled_rubber_1), shape="circle")
        if plan.product == "Plastic":
            dot.node("N_P2", item_label("Plastic", 60.0 * plan.m_recycled_plastic_2), shape="circle")

    if plan.use_packaged_dilution:
        dot.node("N_PW", item_label("Packaged Water", 60.0 * plan.m_packaged_water_packager), shape="circle")
        dot.node("N_PF", item_label("Packaged Fuel", 60.0 * plan.m_packaged_dilution_refinery), shape="circle")

    dot.node("R_BASE", recipe_label("Refinery", plan.m_base_rubber), shape="box")
    if plan.use_packaged_dilution:
        dot.node("R_PACK_WATER", recipe_label("Packager", plan.m_packaged_water_packager), shape="box")
        dot.node("R_DILUTE_PACKAGED", recipe_label("Refinery", plan.m_packaged_dilution_refinery), shape="box")
        dot.node("R_UNPACKAGE_FUEL", recipe_label("Packager", plan.m_unpackaged_fuel_packager), shape="box")
    else:
        dot.node("R_DILUTE", recipe_label("Blender", plan.m_blender_diluted_fuel), shape="box")

    if plan.mode == "2.0":
        dot.node("R_RP1", recipe_label("Refinery", plan.m_recycled_plastic_1), shape="box")
        dot.node("R_RR1", recipe_label("Refinery", plan.m_recycled_rubber_1), shape="box")
        if plan.m_recycled_plastic_2 > 0:
            dot.node("R_RP2", recipe_label("Refinery", plan.m_recycled_plastic_2), shape="box")
            dot.node("N_P2", item_label("Plastic", 60.0 * plan.m_recycled_plastic_2), shape="circle")
    else:
        dot.node("R_RR1", recipe_label("Refinery", plan.m_recycled_rubber_1), shape="box")
        if plan.product == "Plastic":
            dot.node("R_RP2", recipe_label("Refinery", plan.m_recycled_plastic_2), shape="box")

    dot.node("OUT", item_label(plan.product, plan.target_rate), shape="doublecircle")

    dot.edge("N_CRUDE", "R_BASE")
    if plan.mode == "2.0":
        dot.edge("R_BASE", "N_R0")
    else:
        dot.edge("R_BASE", "N_P0")
    dot.edge("R_BASE", "N_HOR")

    if plan.use_packaged_dilution:
        dot.edge("N_WATER", "R_PACK_WATER")
        dot.edge("R_PACK_WATER", "N_PW")
        dot.edge("N_HOR", "R_DILUTE_PACKAGED")
        dot.edge("N_PW", "R_DILUTE_PACKAGED")
        dot.edge("R_DILUTE_PACKAGED", "N_PF")
        dot.edge("N_PF", "R_UNPACKAGE_FUEL")
        dot.edge("R_UNPACKAGE_FUEL", "N_FUEL")
    else:
        dot.edge("N_HOR", "R_DILUTE")
        dot.edge("N_WATER", "R_DILUTE")
        dot.edge("R_DILUTE", "N_FUEL")

    if plan.mode == "2.0":
        dot.edge("N_R0", "R_RP1")
        dot.edge("N_FUEL", "R_RP1")
        dot.edge("R_RP1", "N_P1")

        dot.edge("N_P1", "R_RR1")
        dot.edge("N_FUEL", "R_RR1")
        dot.edge("R_RR1", "N_R1")

        if plan.product == "Rubber":
            dot.edge("N_R0", "OUT")
            dot.edge("N_R1", "OUT")
        else:
            dot.edge("N_P1", "OUT")
            dot.edge("N_R1", "R_RP2")
            dot.edge("N_FUEL", "R_RP2")
            dot.edge("R_RP2", "N_P2")
            dot.edge("N_P2", "OUT")
    else:
        dot.edge("N_P0", "R_RR1")
        dot.edge("N_FUEL", "R_RR1")
        dot.edge("R_RR1", "N_R1")
        if plan.product == "Rubber":
            dot.edge("N_R1", "OUT")
        else:
            dot.edge("N_P0", "OUT")
            dot.edge("N_R1", "R_RP2")
            dot.edge("N_FUEL", "R_RP2")
            dot.edge("R_RP2", "N_P2")
            dot.edge("N_P2", "OUT")

    render_name = out_name if out_name.endswith(".gv") else f"{out_name}.gv"
    dot.render(filename=render_name, directory=out_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Oil-specialized planner (no-loop single-product modes: 2.0 / 1.3)."
    )
    parser.add_argument(
        "--mode",
        default="2.0",
        choices=["2.0", "1.3"],
        help="Production mode.",
    )
    parser.add_argument(
        "product",
        choices=["Rubber", "Plastic", "rubber", "plastic"],
        help="Target product type (Rubber or Plastic)",
    )
    parser.add_argument("rate", type=float, help="Target output rate (/min)")
    parser.add_argument(
        "--out",
        default="output/oil_plan",
        help="Output path prefix for graphviz render (default: output/oil_plan)",
    )
    parser.add_argument(
        "--packaged",
        action="store_true",
        help="Use Alternate: Diluted Packaged Fuel route instead of Blender diluted fuel.",
    )
    args = parser.parse_args()

    plan = build_plan(args.mode, args.product, args.rate, args.packaged)
    render_2x_plan(plan, args.out)

    print(f"mode: {args.mode}")
    print(f"product: {plan.product}")
    print(f"target_rate: {plan.target_rate:.3f}/min")
    print(f"crude_oil_in: {plan.crude_oil:.3f}/min")
    print(f"water_in: {plan.water:.3f}/min")
    print(f"power: {total_power_mw(plan):.3f} MW")
    print("machines:")
    print(f"  crude_to_base_refinery: {plan.m_base_rubber:.3f}")
    if plan.use_packaged_dilution:
        print(f"  packaged_water_packager: {plan.m_packaged_water_packager:.3f}")
        print(f"  diluted_packaged_fuel_refinery: {plan.m_packaged_dilution_refinery:.3f}")
        print(f"  unpackage_fuel_packager: {plan.m_unpackaged_fuel_packager:.3f}")
    else:
        print(f"  diluted_fuel_blender: {plan.m_blender_diluted_fuel:.3f}")
    if plan.m_recycled_plastic_1 > 0:
        print(f"  recycled_plastic_1_refinery: {plan.m_recycled_plastic_1:.3f}")
    if plan.m_recycled_rubber_1 > 0:
        print(f"  recycled_rubber_1_refinery: {plan.m_recycled_rubber_1:.3f}")
    if plan.m_recycled_plastic_2 > 0:
        print(f"  recycled_plastic_2_refinery: {plan.m_recycled_plastic_2:.3f}")
    print(f"graphviz: {args.out}.gv (and rendered output)")


if __name__ == "__main__":
    main()
