"""JSON-only artifacts; no rendering dependencies."""
import json
from pathlib import Path

def load_inputs(root):
    return {name: json.loads((Path(root) / "fixtures" / (name + ".json")).read_text())
            for name in ("evidence", "content", "presentation_plan", "theme")}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def semantic_manifest(inputs, composition):
    return {"schema_version": 1, "validated_inputs": inputs, "composition": composition}
