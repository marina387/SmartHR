"""One command for application checks; never starts model training or a live server."""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-javascript', action='store_true', help='Explicitly omit Node.js syntax checks')
    args = parser.parse_args()
    files = [ROOT / 'app.py', ROOT / 'run_smarthr.py', Path(__file__).resolve()]
    files += sorted((ROOT / 'src').rglob('*.py')) + sorted((ROOT / 'migrations').rglob('*.py'))
    for path in files:
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    print(f'Python syntax: {len(files)} files OK', flush=True)
    if args.skip_javascript:
        print('JavaScript syntax: explicitly omitted', flush=True)
    else:
        node = shutil.which('node')
        if not node:
            print('Node.js is required for JavaScript checks. Install it or use --skip-javascript explicitly.')
            return 1
        javascript = sorted((ROOT / 'src/static/js').glob('*.js'))
        for path in javascript:
            subprocess.run([node, '--check', str(path)], check=True, cwd=ROOT)
        print(f'JavaScript syntax: {len(javascript)} files OK', flush=True)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True, cwd=ROOT)
    folder = ROOT / 'data/test-runs'
    folder.mkdir(parents=True, exist_ok=True)
    report = Path(tempfile.mkdtemp(prefix='check-', dir=folder)) / 'results.xml'
    print(f'Application tests; JUnit report: {report}', flush=True)
    return subprocess.call([sys.executable, '-m', 'pytest', '-q', '--tb=short',
                            f'--junitxml={report}'], cwd=ROOT)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, SyntaxError, subprocess.CalledProcessError) as error:
        print(f'Checks failed: {error}', file=sys.stderr)
        raise SystemExit(1)
