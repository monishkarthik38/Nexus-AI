"""Train the NEXUS experimental claim-evidence verifier.

Run from the backend directory:
    python -m scripts.train_evidence_verifier
"""

import argparse
import json
from pathlib import Path

from app.evaluation.evidence_verifier import train_verifier

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BACKEND_DIR / "data" / "evidence_verifier_seed.jsonl"
DEFAULT_OUTPUT = BACKEND_DIR / "models" / "evidence_verifier.joblib"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Labeled JSONL claim/passage dataset")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path for the trained model artifact")
    parser.add_argument("--test-dataset", type=Path, help="Optional independent JSONL test set; document IDs must not overlap training data")
    parser.add_argument("--test-size", type=float, default=0.25, help="Fraction held out for evaluation (0 < value < 1)")
    args = parser.parse_args()

    if not 0 < args.test_size < 1:
        parser.error("--test-size must be greater than 0 and less than 1")

    report = train_verifier(args.dataset, args.output, test_size=args.test_size, test_dataset_path=args.test_dataset)
    print(json.dumps(report, indent=2))
    print("\nExperimental baseline only: label more representative examples and evaluate on a separate, unseen dataset before relying on predictions.")


if __name__ == "__main__":
    main()
