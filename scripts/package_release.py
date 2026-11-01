"""Collect distribution notices and package the dynamically linked Windows app."""
from pathlib import Path
import importlib.metadata as metadata
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/'dist/InkOCR'
def main():
    if not (APP/'InkOCR.exe').exists(): raise SystemExit('Build dist/InkOCR/InkOCR.exe first.')
    documents = ('LICENSE', 'README.md', 'README.en.md', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md', 'CONTRIBUTING.md')
    for name in documents:
        shutil.copy2(ROOT/name, APP/name)
    for folder in ('docs', 'examples'):
        shutil.copytree(ROOT/folder, APP/folder, dirs_exist_ok=True)
    notices = APP/'third-party-licenses'
    for dist in metadata.distributions():
        name = dist.metadata.get('Name', 'unknown')
        package = notices/name
        package.mkdir(parents=True, exist_ok=True)
        (package/'PACKAGE.txt').write_text(f'{name}=={dist.version}\n', encoding='utf-8')
        for file in dist.files or []:
            if any(word in file.name.lower() for word in ('license', 'copying', 'notice')):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = package/str(file).replace('..', '_')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    # Source is included alongside the dynamic Qt libraries for inspection/rebuilds.
    source_root = APP/'source'
    source_root.mkdir(exist_ok=True)
    for name in ('app.py', 'requirements.txt', 'requirements-dev.txt', 'requirements-lock.txt', *documents):
        shutil.copy2(ROOT/name, source_root/name)
    for folder in ('scripts', 'assets', 'tests', 'docs', 'examples'):
        shutil.copytree(ROOT/folder, source_root/folder, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
    archive = ROOT/'dist/InkOCR-Windows-x64.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=5) as output:
        for file in APP.rglob('*'):
            if file.is_file(): output.write(file, file.relative_to(APP.parent))
    print(archive)

if __name__ == '__main__': main()
