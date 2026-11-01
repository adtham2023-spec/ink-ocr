import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import socket
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtTest import QTest
from app import Window, configure_fonts, to_simplified

app = QApplication([])
configure_fonts(app)
QMessageBox.question = lambda *args, **kwargs: QMessageBox.StandardButton.Discard
errors = []
QMessageBox.warning = lambda *args, **kwargs: errors.append(str(args[2]))
def blocked(*args, **kwargs): raise AssertionError('Network access is forbidden')
socket.socket.connect = blocked
socket.create_connection = blocked
assert to_simplified('繁體中文與電子書掃描辨識，臺灣學習 English 123') == '繁体中文与电子书扫描辨识，台湾学习 English 123'

w = Window()
w.show()
pdf = Path('work/pdf-test/扫描书样本.pdf').resolve()
w.add_files([str(pdf)])
assert w.default_project_name() == '扫描书样本.inkocr'
box = [[95, 100], [700, 100], [700, 165], [95, 165]]
sample = {'text':'繁體中文與電子書\nEnglish 123', 'seconds':0.1,
          'boxes':[[box, '繁體中文與電子書', 0.97],
                   [[[95,210],[700,210],[700,265],[95,265]], 'English 123', 0.99]]}
w.on_result(0, sample)
w.on_result(1, sample)
assert w.entries[0]['text'] == '繁体中文与电子书\nEnglish 123'
assert w.entries[0]['lines'][0]['original'] == '繁體中文與電子書'
assert w.entries[0]['lines'][0]['box'] == box

# A real click on Next line crosses the page boundary and selects the first row.
next_button = next(b for b in w.findChildren(QPushButton) if b.text() == '↓ 下一行')
w.files.setCurrentRow(0)
w.pick_line(1)
QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
assert w.files.currentRow() == 1 and w.current_line == 0
assert w.preview.selected == 0
# The second boundary goes to an unrecognized page and starts local OCR.
w.pick_line(1)
QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
assert w.files.currentRow() == 2 and w.worker.isRunning()
loop = QEventLoop()
w.worker.finished.connect(loop.quit)
QTimer.singleShot(120000, loop.quit)
loop.exec()
assert not w.worker.isRunning()
app.processEvents()
assert w.entries[2]['state'].startswith('已完成') and w.current_line == 0
w.pick_line(w.table.rowCount()-1)
QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
assert w.files.currentRow() == 2 and '最后一页' in w.status.text()

# If navigation happens while another OCR job is active, defer the next-page
# recognition until that job finishes instead of leaving the new page pending.
w.entries[2]['state'] = '待识别'
w.files.setCurrentRow(1)
w.pick_line(w.table.rowCount()-1)
real_worker = w.worker
class BusyWorker:
    def isRunning(self): return True
w.worker = BusyWorker()
QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
assert w.pending_navigation == 2 and w.files.currentRow() == 2
w.worker = real_worker
w.done()
app.processEvents()
assert w.worker.isRunning()
loop.exec()
app.processEvents()
assert w.entries[2]['state'].startswith('已完成') and w.current_line == 0
w.pending_navigation = 2
w.stop()
assert w.pending_navigation is None

# Turning conversion off preserves traditional OCR; the manual button converts
# already recognized text without changing coordinates or the OCR baseline.
w.simplify_check.setChecked(False)
w.on_result(1, sample)
assert w.entries[1]['text'].startswith('繁體')
w.files.setCurrentRow(1)
w.simplify_current()
assert w.entries[1]['text'].startswith('繁体')
assert w.entries[1]['lines'][0]['original'].startswith('繁體')
assert w.entries[1]['lines'][0]['box'] == box
assert w.editor.toPlainText() == w.entries[1]['text']
w.copy_text()
assert app.clipboard().text().startswith('繁体')

# Inspect the actual default filename passed to the Save dialog.
saved_defaults = []
project = Path('work/pdf-test/扫描书样本-v4.inkocr').resolve()
def save_dialog(*args, **kwargs):
    saved_defaults.append(args[2])
    return str(project), ''
QFileDialog.getSaveFileName = save_dialog
assert w.save_project()
assert saved_defaults == ['扫描书样本.inkocr']
# Autosave must keep the chosen path and must never reopen the dialog.
w.mark_dirty()
assert w.save_project(automatic=True)
assert len(saved_defaults) == 1
data = json.loads(project.read_text(encoding='utf-8'))
assert data['settings']['simplify_after_ocr'] is False
other = Window()
assert other.load_project(str(project))
assert not other.simplify_check.isChecked()
assert other.entries[1]['text'].startswith('繁体')
other.close()

# Loading a pre-v4 progress file preserves existing corrections.
data.pop('settings')
legacy = Path('work/pdf-test/legacy-v3.inkocr')
legacy.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
other = Window()
assert other.load_project(str(legacy)) and other.simplify_check.isChecked()
assert other.entries[1]['text'] == data['entries'][1]['text']
other.close()
assert not errors, errors
w.simplify_check.setChecked(True)
w.save_project(automatic=True)
w.files.setCurrentRow(1)
w.pick_line(0)
app.processEvents()
w.grab().save('outputs/连续校对繁转简预览.png')
w.close()
print('PASS: click-to-next-page, pending-page automatic OCR, end-of-book boundary, offline t2s, toggle/manual conversion, original boxes, filename defaults, autosave, v3 compatibility')
