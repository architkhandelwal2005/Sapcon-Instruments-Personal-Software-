"""Query the relationship graph: path between two entities by name, or
centrality rankings (coarse total degree, or relation-type + direction
specific counts).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection
from app.graph.centrality import relation_type_counts, total_degree
from app.graph.traversal import find_path


def get_entity_id_by_name(conn, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute("select id from entities where canonical_name = %s", (name,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"No entity found with canonical_name = {name!r}")
        return str(row[0])


def get_entity_name(conn, entity_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("select canonical_name from entities where id = %s", (entity_id,))
        return cur.fetchone()[0]


def cmd_path(args) -> None:
    conn = get_connection()
    start_id = get_entity_id_by_name(conn, args.start)
    end_id = get_entity_id_by_name(conn, args.end)
    path = find_path(conn, start_id, end_id, max_depth=args.max_depth)

    if path is None:
        print(f"No path found between {args.start!r} and {args.end!r} within depth {args.max_depth}.")
    elif not path.steps:
        print("Same entity.")
    else:
        parts = [get_entity_name(conn, path.node_ids[0])]
        for step in path.steps:
            arrow = "<-" if step.reversed else "->"
            parts.append(f" --[{step.relation_type}, {step.provenance}]{arrow} {get_entity_name(conn, step.to_id)}")
        print("".join(parts))
    conn.close()


def cmd_degree(args) -> None:
    conn = get_connection()
    rows = total_degree(conn, limit=args.limit)
    print(f"{'Entity':40} {'Type':10} Degree")
    for name, entity_type, degree in rows:
        print(f"{name:40} {entity_type:10} {degree}")
    conn.close()


def cmd_relation_counts(args) -> None:
    conn = get_connection()
    rows = relation_type_counts(conn, relation_type=args.relation_type, direction=args.direction, limit=args.limit)
    print(f"{'Entity':40} {'Type':10} {'Relation':20} {'Dir':4} Count")
    for name, entity_type, relation_type, direction, cnt in rows:
        print(f"{name:40} {entity_type:10} {relation_type:20} {direction:4} {cnt}")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the relationship graph.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_path = sub.add_parser("path", help="Find how two entities connect")
    p_path.add_argument("start")
    p_path.add_argument("end")
    p_path.add_argument("--max-depth", type=int, default=6)
    p_path.set_defaults(func=cmd_path)

    p_degree = sub.add_parser("degree", help="Coarse total-degree ranking (relation-agnostic)")
    p_degree.add_argument("--limit", type=int, default=20)
    p_degree.set_defaults(func=cmd_degree)

    p_rel = sub.add_parser("relation-counts", help="Relation-type + direction specific counts")
    p_rel.add_argument("--relation-type", default=None)
    p_rel.add_argument("--direction", choices=["in", "out"], default=None)
    p_rel.add_argument("--limit", type=int, default=20)
    p_rel.set_defaults(func=cmd_relation_counts)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
