"""Regression: real drops preserve regions, undo/rotation persist, both engines run offline."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import socket
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from app import Window, read_source, source_ref, make_engine, recognize

app = QApplication([])
QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Discard
w = Window(); w.show()
source = str(Path('outputs/中英文测试图片.png').resolve())
w.add_files([source])
w.on_result(0, json.loads(Path('work/packaged-offline.json').read_text(encoding='utf-8')))
app.processEvents()
original = deepcopy(w.entries[0]['lines'])
mime = QMimeData(); mime.setData(w.table.MIME, f'{id(w.table)}:0'.encode())
rect = w.table.visualRect(w.table.model().index(2, 0))
drop = QDropEvent(QPointF(rect.center().x(), rect.bottom()-1), Qt.DropAction.MoveAction,
                  mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
w.table.dropEvent(drop)
assert drop.isAccepted()
assert w.entries[0]['lines'][2] == original[0], 'Move complete record, including original, confidence and polygon'
assert w.entries[0]['text'].splitlines()[2] == original[0]['text']
w.undo_page(); assert w.entries[0]['lines'] == original
w.pick_line(0); w.merge_line()
assert len(w.entries[0]['lines']) == len(original)-1
assert original[0]['text'] in w.entries[0]['lines'][0]['text']
w.undo_page(); w.pick_line(0); w.delete_line()
assert len(w.entries[0]['lines']) == len(original)-1
w.undo_page()
w.add_line()
app.processEvents()
from PySide6.QtTest import QTest
QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
assert len(w.entries[0]['lines']) == len(original)+1
w.undo_page()
before = read_source(source_ref(w.entries[0]))
w.rotate_page(90)
w.add_files([source])
assert len(w.entries) == 1, 'Rotating a page must not bypass duplicate-source detection'
after = read_source(source_ref(w.entries[0]))
assert after.shape[:2] == before.shape[:2][::-1]
assert (after[0, -1] == before[0, 0]).all()
assert w.entries[0]['text'] == '\n'.join(x['text'] for x in original)
w.engine_combo.setCurrentText('Tesseract'); w.language_combo.setCurrentIndex(2)
target = Path('work/page-tools.inkocr').resolve()
w.project_file = str(target); assert w.save_project(automatic=True)
other = Window(); assert other.load_project(str(target))
assert other.entries[0]['rotation'] == 90
assert other.engine_combo.currentText() == 'Tesseract'
assert other.language_combo.currentData() == 'eng'
other.undo_page()
assert other.entries[0].get('rotation', 0) == 0
assert other.entries[0]['lines'] == original
other.project_file = None; other.dirty = False; other.close()
w.undo_page()
socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError('OCR attempted network access'))
for language in ('eng', 'chi_sim+eng', 'chi_tra+eng'):
    result = recognize(make_engine('Tesseract', language), source)
    assert result['boxes'] and 'English words' in result['text'], result['text']
    assert all(0 <= line[2] <= 1 for line in result['boxes'])
# Force re-OCR must restore corrections through page history.
w.page_snapshot()
w.start(True, force=True)
assert w.worker.wait(90000)
app.processEvents()
assert w.entries[0]['ocr_engine'] == 'Tesseract'
w.undo_page(); assert w.entries[0]['lines'] == original
# An actually sideways input becomes readable after a per-page rotation.
from PIL import Image
sideways = Path('work/sideways.png').resolve()
with Image.open(source) as image: image.transpose(Image.Transpose.ROTATE_270).save(sideways)
w.add_files([str(sideways)])
w.files.setCurrentRow(1)
w.rotate_page(-90)
w.start(True, force=True)
assert w.worker.wait(90000)
app.processEvents()
assert 'English words' in w.entries[1]['text']
assert w.entries[1]['rotation'] == 270
# PDF rotation is independent per page and never changes the source file.
pdf = next(Path('work').rglob('*.pdf'))
data = pdf.read_bytes()
normal = read_source(dict(path=str(pdf.resolve()), page=0))
rotated = read_source(dict(path=str(pdf.resolve()), page=0, rotation=90))
assert rotated.shape[:2] == normal.shape[:2][::-1]
assert pdf.read_bytes() == data
# A failed re-recognition keeps completed corrections out of batch resume.
w.files.setCurrentRow(0)
w.on_error(0, 'test failure')
assert w.entries[0]['lines'] == original
assert w.entries[0]['state'].startswith('已保留原文')
w.project_file = None; w.dirty = False; w.close()
print('PASS: row drop, add/delete/merge/undo, rotation persistence, offline Tesseract languages and forced rerun')
