"""
Create a deterministic 67/33 improvement/holdout split of golden_dataset_v2.json.
Seed is fixed so the split is reproducible across runs.

Output:
  evals/improvement_set.json  (70 cases — used during prompt tuning)
  evals/holdout_set.json      (34 cases — never seen until final validation)
"""
import json
import random
from pathlib import Path

SEED = 42  # ponytail: fixed seed for reproducibility, change only if dataset changes
HOLDOUT_RATIO = 0.33

dataset_path = Path(__file__).parent / "golden_dataset_v2.json"
with open(dataset_path) as f:
    dataset = json.load(f)

# Stratified-ish: shuffle then split (dataset is already balanced by category)
rng = random.Random(SEED)
indices = list(range(len(dataset)))
rng.shuffle(indices)

holdout_size = int(len(dataset) * HOLDOUT_RATIO)
holdout_indices = set(indices[:holdout_size])

improvement = [dataset[i] for i in range(len(dataset)) if i not in holdout_indices]
holdout = [dataset[i] for i in range(len(dataset)) if i in holdout_indices]

out_dir = Path(__file__).parent
with open(out_dir / "improvement_set.json", "w") as f:
    json.dump(improvement, f, indent=2)
with open(out_dir / "holdout_set.json", "w") as f:
    json.dump(holdout, f, indent=2)

# Summary
imp_pass = sum(1 for c in improvement if c["expected_status"] == "PASS")
hold_pass = sum(1 for c in holdout if c["expected_status"] == "PASS")
print(f"Improvement set: {len(improvement)} cases ({imp_pass} PASS, {len(improvement)-imp_pass} FAIL)")
print(f"Holdout set:     {len(holdout)} cases ({hold_pass} PASS, {len(holdout)-hold_pass} FAIL)")
