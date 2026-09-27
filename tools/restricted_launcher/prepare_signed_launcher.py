"""Copy/sign a launcher and recollect offline evidence; never execute it.

Run with PYTHONPATH=src and python -B. Existing deployment files are preserved.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from presentation_agent import _deployment_evidence as deployment
from presentation_agent import _launch_policy as policy
from presentation_agent import _startup_inventory as startup
from presentation_agent.evidence import canonical_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.absolute()
    if (output.resolve() != output or not output.is_relative_to(root / 'build')
            or output == root / 'build' or output.exists()):
        parser.error('output must be a new directory beneath project build/')
    inputs = json.loads(args.inputs.read_bytes())
    output.mkdir(parents=True)
    launcher = output / 'launcher'
    shutil.copyfile(inputs['native_files']['launcher'], launcher)
    launcher.chmod(0o755)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--options', 'runtime', '--identifier',
                    'org.professionalpresentationagent.launcher', '--timestamp=none',
                    str(launcher)], check=True, capture_output=True, env={})
    policy._signature(launcher)
    for role in ('launcher', 'bootstrap'):
        inputs['native_files'][role] = str(launcher)
    build = json.loads(Path(inputs['build_evidence']).read_bytes())
    parameters = (build, inputs['build_files'], inputs['native_files'],
                  inputs['module_paths'], inputs['runtime'])
    print('Collecting signed deployment evidence', flush=True)
    expected = deployment.collect(*parameters)
    print('Collecting launcher policy evidence', flush=True)
    evidence = policy.collect(expected, *parameters)
    print('Recollecting to verify retained identity', flush=True)
    policy.verify(evidence, expected, *parameters)
    inventory = startup.collect(expected, *parameters)
    (output / 'startup-inventory.bin').write_bytes(inventory)
    for name, value in (('inputs.json', inputs),
                        ('deployment-evidence.json', expected),
                        ('launch-policy-evidence.json', evidence)):
        (output / name).write_bytes(canonical_bytes(value))
    print('Signed launcher identity recollected and verified; qualification not established.')


if __name__ == '__main__':
    main()
