import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtCore import QEventLoop, QTimer
from app import Window, configure_fonts, read_source, make_engine, recognize

app = QApplication([])
configure_fonts(app)
QMessageBox.question = lambda *args, **kwargs: QMessageBox.StandardButton.Discard
messages = []
QMessageBox.warning = lambda *args, **kwargs: messages.append(args[2])
w = Window()
w.show()
pdf = str(Path('work/pdf-test/扫描书样本.pdf').resolve())
w.add_files([pdf, pdf])
assert len(w.entries) == 3, len(w.entries)
assert [e['page'] for e in w.entries] == [0, 1, 2]
assert w.page_spin.maximum() == 3
assert w.source_pix.width() > 1500
# Every preview is rendered in the same coordinate system used by the OCR.
w.move_page(1)
assert w.files.currentRow() == 1 and '第 2 页' in w.info.text()
first_pixels = read_source({'path':pdf, 'page':0})
second_pixels = read_source({'path':pdf, 'page':1})
assert first_pixels.shape == second_pixels.shape
assert (first_pixels != second_pixels).any()

loop = QEventLoop()
w.worker.finished.connect(loop.quit)
def wait():
    QTimer.singleShot(120000, loop.quit)
    loop.exec()
    assert not w.worker.isRunning(), 'Worker timed out'
    app.processEvents()

# Current-page recognition leaves all other pages pending.
w.start(True)
wait()
assert w.entries[1]['state'].startswith('已完成')
assert w.entries[0]['state'] == w.entries[2]['state'] == '待识别'
assert 'Page2/3' in w.entries[1]['text'].replace(' ', '')
original_box = w.entries[1]['lines'][0]['box']
w.pick_line(0)
w.table.item(0, 2).setText('第二页已人工校对 Page two corrected')

# Saving and reopening persists corrections, bounding boxes, page and pending jobs.
project = Path('work/pdf-test/book.inkocr').resolve()
QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(project), '')
assert w.save_project()
assert project.exists() and not w.dirty
other = Window()
other.show()
assert other.load_project(str(project)), messages
assert len(other.entries) == 3 and other.files.currentRow() == 1
assert other.entries[1]['lines'][0]['text'].startswith('第二页已人工校对')
assert other.entries[1]['lines'][0]['box'] == original_box
other.close()

# Stop deterministically after first new result; remaining work is resumable.
def stop_after_first(index, result): w.worker.requestInterruption()
w.worker.result.connect(stop_after_first, type=__import__('PySide6.QtCore', fromlist=['Qt']).Qt.ConnectionType.DirectConnection)
w.start()
wait()
w.worker.result.disconnect(stop_after_first)
assert w.entries[0]['state'].startswith('已完成')
assert w.entries[2]['state'] == '待识别'
w.start()
wait()
assert all(e['state'].startswith('已完成') for e in w.entries)
assert w.entries[1]['lines'][0]['text'].startswith('第二页已人工校对'), 'Resume must not overwrite corrections'
assert not list(project.parent.glob('book.inkocr.*.tmp'))
saved = json.loads(project.read_text(encoding='utf-8'))
assert all(e['state'].startswith('已完成') for e in saved['entries'])

# Full-book export has all three page labels in order and the corrected text.
export = Path('work/pdf-test/book.txt').resolve()
QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(export), '')
w.export_all()
text = export.read_text(encoding='utf-8-sig')
assert text.index('第 1 页') < text.index('第 2 页') < text.index('第 3 页')
assert '第二页已人工校对' in text

# Invalid/missing original files are rejected without replacing existing work.
bad = dict(saved)
bad['entries'] = [dict(saved['entries'][0], path='Z:/does-not-exist.pdf')]
invalid = Path('work/pdf-test/invalid.inkocr')
invalid.write_text(json.dumps(bad), encoding='utf-8')
assert not w.load_project(str(invalid))
assert len(w.entries) == 3
w.files.setCurrentRow(1)
w.pick_line(0)
w.grab().save('outputs/PDF校对界面预览.png')
assert not w.dirty
w.close()
print('PASS: 3-page scanned PDF, page navigation, current-page OCR, stop/resume, corrected project restore/autosave, ordered export, missing-source validation')
