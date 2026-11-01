"""Run the regression scripts in an isolated temporary workspace on Windows."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UI = ['test_correction.py', 'test_alignment.py', 'test_keyboard.py', 'test_comparison_modes.py']
INTEGRATION = ['test_app.py', 'test_pdf.py', 'test_book_v4.py', 'test_score_filter.py']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=['all', 'ui', 'integration'], default='all')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('The current regression fixtures use Windows CJK fonts. Run on Windows with Python 3.12.')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8')
    with tempfile.TemporaryDirectory(prefix='ink-ocr-tests-') as temporary:
        folder = Path(temporary)
        (folder/'work').mkdir()
        (folder/'outputs').mkdir()
        shutil.copy2(ROOT/'app.py', folder/'work/app.py')
        for source in (ROOT/'tests').glob('*.py'):
            shutil.copy2(source, folder/'work'/source.name)
        def run(*arguments):
            print('RUN', ' '.join(arguments), flush=True)
            subprocess.run([sys.executable, *arguments], cwd=folder, env=env, check=True, timeout=240)
        run('work/make_sample.py')
        run('work/make_pdf_sample.py')
        run('work/app.py', '--self-test', 'outputs/中英文测试图片.png', 'work/packaged-offline.json')
        files = UI+INTEGRATION if args.suite == 'all' else UI if args.suite == 'ui' else INTEGRATION
        for filename in files: run('work/'+filename)
    print('PASS: selected regression suite completed in an isolated workspace', flush=True)

if __name__ == '__main__': main()
