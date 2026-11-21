"""Regenerate data/humor_playbook.json from the hand-authored shapes.

The sales CSV is not a joke sample, so this snapshot no longer copies its lines.
A nightly job can run `python scripts/regenerate_humor_playbook.py`.
"""

from pathlib import Path

from merchandise_discovery.domain.humor_playbook import write_playbook
from merchandise_discovery.infrastructure.humor_reference_loader import parse_humor_reference_csv

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    csv_path = ROOT / "data" / "humor_references.csv"
    json_path = ROOT / "data" / "humor_playbook.json"
    references = parse_humor_reference_csv(csv_path.read_text(encoding="utf-8-sig"))
    playbook = write_playbook(references, json_path)
    print(f"Wrote {json_path} ({len(playbook['patterns'])} patterns)")


if __name__ == "__main__":
    main()
