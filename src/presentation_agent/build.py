"""Run with PYTHONPATH=src .venv/bin/python -m presentation_agent.build."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from .models import load_inputs, semantic_manifest
from .validate import validate
from .compose import compose
from .pptx_renderer import render
from .qa import structural_qa


def build(root):
    root = Path(root)
    inputs = validate(load_inputs(root))
    composition = compose(inputs)
    out = root / 'output' / 'milestone1'
    out.mkdir(parents=True, exist_ok=True)
    render(composition, out / 'deck.pptx')
    with TemporaryDirectory(dir=out) as temporary:
        rebuilt = Path(temporary) / 'rebuilt.pptx'
        render(compose(load_inputs(root)), rebuilt)
        report = structural_qa(inputs, composition, out / 'deck.pptx', rebuilt)
    for name, value in [('composition',composition), ('semantic_manifest',semantic_manifest(inputs,composition)), ('structural_qa',report)]:
        (out / (name+'.json')).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    if not report['passed']:
        raise RuntimeError('Structural QA failed: '+str(report['checks']))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    report = build(args.root)
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
