"""Regenerate data/humor_playbook.json from data/humor_references.csv.

A nightly job can run `python scripts/regenerate_humor_playbook.py`.
The Streamlit run does not write this file; it rebuilds the same patterns
from the rows it loaded for that run.
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
