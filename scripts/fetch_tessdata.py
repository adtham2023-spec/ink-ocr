"""Fetch pinned official Apache-2.0 language models at setup/build time only."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '87416418657359cb625c412a48b6e1d6d41c29bd'

def main():
    folder = ROOT/'assets/tessdata'
    folder.mkdir(parents=True, exist_ok=True)
    manifest = ROOT/'assets/tessdata-manifest.json'
    expected = json.loads(manifest.read_text()) if manifest.exists() else {}
    hashes = {}
    for name in ('eng', 'chi_sim', 'chi_tra'):
        filename = name+'.traineddata'
        target = folder/filename
        if not target.exists():
            data = urllib.request.urlopen(f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{COMMIT}/{filename}', timeout=120).read()
        else: data = target.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected and digest != expected[filename]: raise RuntimeError('Model checksum mismatch: '+filename)
        target.write_bytes(data)
        hashes[filename] = digest
        print(filename, digest)
    if not expected: manifest.write_text(json.dumps(hashes, indent=2)+'\n')

if __name__ == '__main__': main()
