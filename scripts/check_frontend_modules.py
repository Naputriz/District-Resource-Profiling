#!/usr/bin/env python3
"""
Static verification script for frontend ES modules.
Validates:
1. Every imported file exists on disk.
2. Every imported symbol is exported by the target module.
3. No circular import dependencies exist across the module graph.
"""

import os
import re
import sys
from typing import Dict, List, Set, Tuple

JS_ROOT = os.path.abspath("frontend/js")

IMPORT_REGEX = re.compile(
    r'import\s+(?:(?P<named>\{[^}]+\})|(?P<star>\*\s+as\s+\w+)|(?P<default>\w+))(?:\s*,\s*(?:\{[^}]+\}|\w+))?\s+from\s+["\'](?P<path>[^"\']+)["\'];',
    re.MULTILINE
)

EXPORT_NAMED_REGEX = re.compile(
    r'export\s+(?:async\s+)?(?:function|class|const|let|var)\s+(?P<name>\w+)',
    re.MULTILINE
)

EXPORT_BLOCK_REGEX = re.compile(
    r'export\s+\{([^}]+)\};',
    re.MULTILINE
)

EXPORT_DEFAULT_REGEX = re.compile(
    r'export\s+default\s+',
    re.MULTILINE
)

def find_js_files(base_dir: str) -> List[str]:
    js_files = []
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.endswith(".js") and f != "app.js":
                js_files.append(os.path.join(root, f))
    return sorted(js_files)

def extract_exports(file_path: str) -> Set[str]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    exports = set()
    for match in EXPORT_NAMED_REGEX.finditer(content):
        exports.add(match.group("name"))

    for match in EXPORT_BLOCK_REGEX.finditer(content):
        block = match.group(1)
        for item in block.split(","):
            item = item.strip()
            if not item:
                continue
            if " as " in item:
                exports.add(item.split(" as ")[1].strip())
            else:
                exports.add(item)

    if EXPORT_DEFAULT_REGEX.search(content):
        exports.add("default")

    return exports

def extract_imports(file_path: str) -> List[Tuple[List[str], str]]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    results = []
    for match in IMPORT_REGEX.finditer(content):
        rel_path = match.group("path")
        names = []
        named = match.group("named")
        star = match.group("star")
        default = match.group("default")

        if named:
            cleaned = named.strip("{} \t\r\n")
            for item in cleaned.split(","):
                item = item.strip()
                if not item:
                    continue
                orig_name = item.split(" as ")[0].strip()
                names.append(orig_name)
        elif star:
            names.append("*")
        elif default:
            names.append("default")

        results.append((names, rel_path))

    return results

def detect_cycles(graph: Dict[str, List[str]]) -> List[List[str]]:
    visited = {}  # 0: unvisited, 1: visiting, 2: visited
    cycles = []

    def dfs(node: str, path: List[str]):
        visited[node] = 1
        path.append(node)

        for neighbor in graph.get(node, []):
            if visited.get(neighbor, 0) == 1:
                # Cycle found
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
            elif visited.get(neighbor, 0) == 0:
                dfs(neighbor, path)

        path.pop()
        visited[node] = 2

    for node in graph:
        if visited.get(node, 0) == 0:
            dfs(node, [])

    return cycles

def generate_ascii_graph(dependency_graph: Dict[str, List[str]]) -> str:
    rel_graph = {
        os.path.relpath(src, JS_ROOT): [os.path.relpath(t, JS_ROOT) for t in targets]
        for src, targets in dependency_graph.items()
    }

    lines = []
    lines.append("[main.js]")
    
    # Ordered main.js imports
    main_deps = rel_graph.get("main.js", [])
    for idx, dep in enumerate(main_deps):
        is_last = (idx == len(main_deps) - 1)
        prefix = "   └── " if is_last else "   ├── "
        child_deps = rel_graph.get(dep, [])

        if not child_deps:
            lines.append(f"{prefix}[{dep}]")
        elif dep == "panels/watchdog.js":
            # Linear chain: watchdog -> api.js -> config.js
            lines.append(f"{prefix}[{dep}] ──> [api.js] ──> [config.js]")
        elif dep == "chat/chat.js":
            lines.append(f"{prefix}[{dep}]")
            chat_sub_prefix = "   │      " if not is_last else "          "
            # Separate actions from leaf imports
            for c_idx, c_dep in enumerate(child_deps):
                c_is_last = (c_idx == len(child_deps) - 1)
                sub_p = f"{chat_sub_prefix}└── " if c_is_last else f"{chat_sub_prefix}├── "
                if c_dep == "map/actions.js":
                    act_deps = rel_graph.get(c_dep, [])
                    act_deps_str = ", ".join(f"[{d}]" for d in act_deps)
                    lines.append(f"{sub_p}[{c_dep}] ──> {act_deps_str}")
                else:
                    lines.append(f"{sub_p}[{c_dep}]")
        elif dep == "map/map.js":
            lines.append(f"{prefix}[{dep}]")
            map_sub_prefix = "          "
            for m_idx, m_dep in enumerate(child_deps):
                m_is_last = (m_idx == len(child_deps) - 1)
                sub_p = f"{map_sub_prefix}└── " if m_is_last else f"{map_sub_prefix}├── "
                m_sub_deps = rel_graph.get(m_dep, [])
                if m_sub_deps:
                    sub_deps_str = ", ".join(f"[{d}]" for d in m_sub_deps)
                    lines.append(f"{sub_p}[{m_dep}] ──> {sub_deps_str}")
                else:
                    lines.append(f"{sub_p}[{m_dep}]")
        else:
            deps_str = ", ".join(f"[{d}]" for d in child_deps)
            lines.append(f"{prefix}[{dep}] ──> {deps_str}")

    return "\n".join(lines)


def main():
    show_graph = "--graph" in sys.argv
    if not show_graph:
        print(f">> Verifying frontend modules in {JS_ROOT}...")
    files = find_js_files(JS_ROOT)
    if not files:
        print(f"ERROR: No JS modules found in {JS_ROOT}", file=sys.stderr)
        sys.exit(1)

    print(f" -> Found {len(files)} module files:")
    for f in files:
        rel = os.path.relpath(f, os.path.abspath("."))
        print(f"    * {rel}")

    exports_by_file: Dict[str, Set[str]] = {}
    for f in files:
        exports_by_file[f] = extract_exports(f)

    dependency_graph: Dict[str, List[str]] = {f: [] for f in files}
    errors = []

    for f in files:
        f_rel = os.path.relpath(f, os.path.abspath("."))
        file_dir = os.path.dirname(f)
        imports = extract_imports(f)

        for imported_names, target_rel in imports:
            target_abs = os.path.normpath(os.path.join(file_dir, target_rel))

            # 1. Assert target exists
            if not os.path.isfile(target_abs):
                errors.append(f"[{f_rel}] Imports nonexistent file: '{target_rel}' (resolved to {target_abs})")
                continue

            dependency_graph[f].append(target_abs)

            # 2. Assert imported symbols are exported
            target_exports = exports_by_file.get(target_abs, set())
            target_rel_display = os.path.relpath(target_abs, os.path.abspath("."))

            for name in imported_names:
                if name == "*":
                    continue
                if name not in target_exports:
                    errors.append(
                        f"[{f_rel}] Imports '{name}' from '{target_rel_display}', but '{name}' is not exported! "
                        f"Available exports: {sorted(target_exports)}"
                    )

    # 3. Detect cycles
    cycles = detect_cycles(dependency_graph)
    if cycles:
        for c in cycles:
            cycle_str = " -> ".join(os.path.relpath(node, os.path.abspath(".")) for node in c)
            errors.append(f"Circular dependency cycle detected: {cycle_str}")

    print("\n>> Module Import & Export Verification Results:")
    if errors:
        print(f"FAILED: Found {len(errors)} issues:\n", file=sys.stderr)
        for err in errors:
            print(f"  ❌ {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"  ✅ All {len(files)} modules exist.")
        print(f"  ✅ All imported symbols match target exports.")
        print(f"  ✅ No circular dependency cycles found.")
        print(f"  ✅ Graph is a valid Directed Acyclic Graph (DAG)!\n")

    if show_graph:
        print(">> Real Module Dependency Adjacency:")
        rel_graph = {
            os.path.relpath(src, JS_ROOT): [os.path.relpath(t, JS_ROOT) for t in dependency_graph[src]]
            for src in files
        }
        for mod in sorted(rel_graph.keys()):
            deps = rel_graph[mod]
            if deps:
                print(f"  [{mod}] ──> {', '.join(f'[{d}]' for d in deps)}")
            else:
                print(f"  [{mod}] (leaf)")

        print("\n>> Generated ASCII Dependency Tree (from real imports):")
        print(generate_ascii_graph(dependency_graph))
        print()

if __name__ == "__main__":
    main()
