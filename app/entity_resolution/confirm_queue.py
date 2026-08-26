from typing import Optional

from app.entity_resolution.matcher import Candidate


def confirm_or_choose(name: str, entity_type: str, candidates: list[Candidate]) -> Optional[str]:
    """Show medium-confidence candidates and ask which one (if any) `name`
    refers to. Returns the chosen candidate's id, or None to create a new
    entity instead."""
    print(f"\nPossible match for '{name}' ({entity_type}):")
    for i, c in enumerate(candidates, start=1):
        alias_note = f", aliases={c.aliases}" if c.aliases else ""
        print(f"  {i}. {c.canonical_name} (score={c.score:.2f}{alias_note})")
    print("  n. None of these — create a new entity")

    while True:
        choice = input("Choice: ").strip().lower()
        if choice == "n":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1].id
        print("Invalid choice, try again.")
