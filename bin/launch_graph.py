#!/usr/bin/env python3
"""
Proof of concept, works but doesn't seem overly useful yet.
Use like so:

python bin/launch_graph.py examples/03_composition.launch.py > graph.dot
dot -Tpng graph.dot -o graph.png

Todo:
- strip comments after function unparsed() arguments
- give special kind to block comments
- make the CFG easier to work with
- find a better representation for export than dot
- write additional handlers for ROS2 launch files (python, xml, yaml)
"""

from typing import Literal
import ast
import sys


CfgNodeKind = Literal[
    "stmt",
    "bl",
    "cond",
    "start",
    "end",
    "nop",
]


class ControlFlowGraph:
    def __init__(self):
        self.nodes: list[int, str, str] = []  # (id, label, kind)
        self.edges: list[int, int, str] = []  # (src, dst, label)
        self.next_id = 0

    def new_node(self, label: str, kind: CfgNodeKind = "stmt") -> int:
        nid = self.next_id
        self.next_id += 1
        self.nodes.append((nid, label, kind))
        return nid

    def add_edge(self, src: int, dst: int, label: str = None):
        self.edges.append((src, dst, label))

    def merge_exits(self, *exit_sets: list[set[int]]) -> set[int]:
        out = set()
        for s in exit_sets:
            out |= set(s)
        return out

    def to_dot(self) -> str:
        lines = [
            "digraph G {",
            '  node [shape=box,fontname="Helvetica"];',
            "  rankdir=TB;",
        ]

        for nid, label, kind in self.nodes:
            shape = {
                "stmt": "box",
                "bl": "ellipse",
                "cond": "diamond",
                "start": "oval",
                "end": "oval",
                "nop": "point",
            }.get(kind, "box")
            safe_label = (label or "").replace('"', r"\"")
            lines.append(f'  n{nid} [shape={shape},label="{safe_label}"];')

        for src, dst, elabel in self.edges:
            lab = f' [label="{elabel}"]' if elabel else ""
            lines.append(f"  n{src} -> n{dst}{lab};")

        lines.append("}")
        return "\n".join(lines)


class BetterLaunchCallTracker:
    def __init__(self):
        self.class_names = {"BetterLaunch"}
        self.instance_names: set[str] = set()

    def feed_import(self, node: ast.AST):
        if isinstance(node, ast.ImportFrom) and node.module == "better_launch":
            for alias in node.names:
                if alias.name == "BetterLaunch":
                    self.class_names.add(alias.asname or alias.name)

    def track_assignment(self, target: ast.AST, value: ast.AST):
        if isinstance(value, ast.Call):
            f = value.func
            if isinstance(f, ast.Name) and f.id in self.class_names:
                if isinstance(target, ast.Name):
                    self.instance_names.add(target.id)

    def track_context_target(self, target: ast.AST, ctx_expr: ast.AST):
        # If the with-context is a BL call and we have "as <name>", track that name too
        if isinstance(ctx_expr, ast.Call) and self.is_bl_call(ctx_expr):
            if isinstance(target, ast.Name):
                self.instance_names.add(target.id)

    def is_bl_call(self, call: ast.Call) -> str:
        f = call.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id in self.instance_names:
                return f.attr
        return None


class CFGBuilder(ast.NodeVisitor):
    def __init__(self, cfg: ControlFlowGraph, bl: BetterLaunchCallTracker):
        self.cfg = cfg
        self.bl = bl
        self.source = ""

    def build_module(self, module: ast.Module):
        for n in module.body:
            if isinstance(n, (ast.ImportFrom, ast.Import)):
                self.bl.feed_import(n)

        start = self.cfg.new_node("START", "start")
        entry, exits = self.build_block(module.body)
        if entry is not None:
            self.cfg.add_edge(start, entry)

        end = self.cfg.new_node("END", "end")
        for e in exits:
            self.cfg.add_edge(e, end)

    def build_block(self, stmts: list[ast.stmt]) -> tuple[int, set[int]]:
        prev_exits: set[int] = None
        entry: int = None

        for s in stmts:
            e_entry, e_exits = self.build_stmt(s)

            if e_entry is None:
                continue

            if entry is None:
                entry = e_entry

            if prev_exits is not None:
                for p in prev_exits:
                    self.cfg.add_edge(p, e_entry)

            prev_exits = e_exits

        if entry is None:
            nop = self.cfg.new_node("", "nop")
            return nop, {nop}

        return entry, prev_exits or set()

    def build_stmt(self, node: ast.stmt) -> tuple[int, set[int]]:
        if isinstance(node, ast.FunctionDef):
            label = f"def {node.name}(" + ", ".join(a.arg for a in node.args.args) + ")"
            fentry = self.cfg.new_node(label, "start")

            b_entry, b_exits = self.build_block(node.body)
            if b_entry is not None:
                self.cfg.add_edge(fentry, b_entry)

            fend = self.cfg.new_node(f"end {node.name}", "end")
            for e in b_exits:
                self.cfg.add_edge(e, fend)

            return fentry, {fend}

        if isinstance(node, ast.If):
            cond_src = ast.get_source_segment(self.source, node.test)
            if not cond_src:
                cond_src = ast.dump(node.test)

            cond = self.cfg.new_node(f"if {cond_src}", "cond")

            then_entry, then_exits = self.build_block(node.body)
            else_entry, else_exits = (
                self.build_block(node.orelse) if node.orelse else (None, set())
            )
            if then_entry is None:
                then_entry, then_exits = self.build_block([])
            if else_entry is None:
                else_entry, else_exits = self.build_block([])

            self.cfg.add_edge(cond, then_entry, "True")
            self.cfg.add_edge(cond, else_entry, "False")

            return cond, self.cfg.merge_exits(then_exits, else_exits)

        if isinstance(node, ast.While):
            test_src = ast.get_source_segment(self.source, node.test)
            if not test_src:
                test_src = ast.dump(node.test)

            cond = self.cfg.new_node(f"while {test_src}", "cond")

            body_entry, body_exits = self.build_block(node.body)
            if body_entry is None:
                body_entry, body_exits = self.build_block([])
            self.cfg.add_edge(cond, body_entry, "True")

            for e in body_exits:
                self.cfg.add_edge(e, cond, "loop")
            end = self.cfg.new_node("while_end", "nop")

            if node.orelse:
                else_entry, else_exits = self.build_block(node.orelse)
                if else_entry is not None:
                    self.cfg.add_edge(cond, else_entry, "False")
                    for e in else_exits:
                        self.cfg.add_edge(e, end)
                else:
                    self.cfg.add_edge(cond, end, "False")
            else:
                self.cfg.add_edge(cond, end, "False")

            return cond, {end}

        if isinstance(node, ast.For):
            tgt_src = ast.get_source_segment(self.source, node.target)
            if not tgt_src:
                tgt_src = ast.dump(node.target)

            iter_src = ast.get_source_segment(self.source, node.iter)
            if not iter_src:
                iter_src = ast.dump(node.iter)

            cond = self.cfg.new_node(f"for {tgt_src} in {iter_src}", "cond")

            body_entry, body_exits = self.build_block(node.body)
            if body_entry is None:
                body_entry, body_exits = self.build_block([])
            self.cfg.add_edge(cond, body_entry, "Iter")

            for e in body_exits:
                self.cfg.add_edge(e, cond, "next")
            end = self.cfg.new_node("for_end", "nop")

            if node.orelse:
                else_entry, else_exits = self.build_block(node.orelse)
                if else_entry is not None:
                    self.cfg.add_edge(cond, else_entry, "Empty")
                    for e in else_exits:
                        self.cfg.add_edge(e, end)
                else:
                    self.cfg.add_edge(cond, end, "Empty")
            else:
                self.cfg.add_edge(cond, end, "Empty")

            return cond, {end}

        if isinstance(node, ast.Return):
            src = ast.get_source_segment(self.source, node) or "return"
            n = self.cfg.new_node(src, "stmt")
            return n, set()

        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr)):
            label_src = (
                ast.get_source_segment(self.source, node) or node.__class__.__name__
            )
            kind = "stmt"

            if isinstance(node, ast.Assign):
                value = node.value
                if isinstance(value, ast.Call):
                    self.bl.track_assignment(node.targets[0], value)
                    meth = self.bl.is_bl_call(value)
                    if meth:
                        args = ", ".join(self.get_call_args(value))
                        kind, label_src = "bl", f"BL.{meth}({args})"

            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                meth = self.bl.is_bl_call(node.value)
                if meth:
                    args = ", ".join(self.get_call_args(node.value))
                    kind, label_src = "bl", f"BL.{meth}({args})"

            n = self.cfg.new_node(label_src, kind)
            return n, {n}

        if isinstance(node, (ast.With, ast.AsyncWith)):
            # Build a single "with ..." entry node that can include multiple items
            labels = []
            is_bl = False

            for item in node.items:
                ctx = item.context_expr
                ctx_src = ast.get_source_segment(self.source, ctx) or ast.dump(ctx)

                if isinstance(ctx, ast.Call):
                    meth = self.bl.is_bl_call(ctx)
                    if meth:
                        args = ", ".join(self.get_call_args(ctx))
                        labels.append(f"BL.{meth}({args})")
                        is_bl = True
                        # track "as <name>" target as a BL-like handle
                        if item.optional_vars:
                            self.bl.track_context_target(item.optional_vars, ctx)
                    else:
                        labels.append(f"with {ctx_src}")
                else:
                    labels.append(f"with {ctx_src}")

            label = " | ".join(labels) if labels else "with"
            kind = "bl" if is_bl else "stmt"

            with_entry = self.cfg.new_node(label, kind)
            body_entry, body_exits = self.build_block(node.body)
            if body_entry is None:
                body_entry, body_exits = self.build_block([])
            self.cfg.add_edge(with_entry, body_entry)

            with_end = self.cfg.new_node("with_end", "nop")
            for e in body_exits:
                self.cfg.add_edge(e, with_end)

            return with_entry, {with_end}

        src = ast.get_source_segment(self.source, node) or node.__class__.__name__
        n = self.cfg.new_node(src, "stmt")
        return n, {n}

    def get_call_args(self, call: ast.Call) -> list[str]:
        args = [ast.unparse(a) for a in call.args]
        args.extend(f"{k.arg}={ast.unparse(k.value)}" for k in call.keywords if k.arg)
        return args


def build_cfg_from_path(path: str, strip_comments: bool = True) -> ControlFlowGraph:
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    if strip_comments:
        # TODO
        pass

    module = ast.parse(source, filename=path, type_comments=True)

    cfg = ControlFlowGraph()
    bl = BetterLaunchCallTracker()
    builder = CFGBuilder(cfg, bl)
    builder.source = source
    builder.build_module(module)

    return cfg


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <python_file.py> > graph.dot")
        return

    cfg = build_cfg_from_path(sys.argv[1])
    print(cfg.to_dot())


if __name__ == "__main__":
    main()
