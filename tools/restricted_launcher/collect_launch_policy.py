"""Write Phase 4.5A4 observation evidence under a new ignored build directory.

Run with PYTHONPATH=src and python -B. This never launches the provider.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from presentation_agent._launch_policy import collect, verify
from presentation_agent.evidence import canonical_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.absolute()
    if (output.resolve() != output or not output.is_relative_to(root / 'build')
            or output == root / 'build' or output.exists()):
        parser.error('output must be a new directory beneath project build/')
    deployment = json.loads(args.deployment.read_bytes())
    inputs = json.loads(args.inputs.read_bytes())
    build = json.loads(Path(inputs['build_evidence']).read_bytes())
    parameters = (deployment, build, inputs['build_files'], inputs['native_files'],
                  inputs['module_paths'], inputs['runtime'])
    print('Collecting launch policy/protection observations', flush=True)
    result = collect(*parameters)
    print('Recollecting to verify deterministic evidence', flush=True)
    verify(result, *parameters)
    payload = canonical_bytes(result)
    output.mkdir(parents=True)
    (output / 'launch-policy-evidence.json').write_bytes(payload)
    (output / 'launch-policy-evidence.sha256').write_text(sha256(payload).hexdigest() + '\n')
    print('Evidence written; qualification not established.')
    for gap in result['deployment']['protection_gaps']:
        print('Protection gap: ' + gap)


if __name__ == '__main__':
    main()
