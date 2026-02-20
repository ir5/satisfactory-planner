import copy
import os
import sys
from collections import defaultdict

try:
    from colorama import Fore, Style, init as colorama_init
except Exception:
    Fore = None
    Style = None

    def colorama_init(*_args, **_kwargs):
        return None

from planner.data import load_recipe_vanilla1_0
from planner.graph import GenGraph
from planner.models import ItemNode, SessionState
from planner.session import (
    build_session_label,
    infer_label_from_graph,
    latest_session_path,
    list_session_paths,
    load_session,
    resolve_session_path,
    save_session,
)


def color_text(text: str, color: str) -> str:
    if Fore is None or Style is None:
        return text
    return f"{color}{text}{Style.RESET_ALL}"


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
                        paths = list_session_paths()
                        if len(paths) == 0:
                            print("No session files found under sessions/.")
                            continue
                        print("Saved sessions (latest first):")
                        for path in paths:
                            print(f"  {os.path.basename(path)}")
                        continue
                    if len(tokens) == 1:
                        path = latest_session_path()
                        if path is None:
                            print("No session files found under sessions/.")
                            continue
                    else:
                        path = resolve_session_path(tokens[1])
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

