import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtTest import QTest
from app import Window, configure_fonts

app = QApplication([])
configure_fonts(app)
QMessageBox.question = lambda *args, **kwargs: QMessageBox.StandardButton.Discard
errors = []
QMessageBox.warning = lambda *args, **kwargs: errors.append(str(args[2]))
w = Window()
w.show()
w.add_files([str(Path('work/pdf-test/扫描书样本.pdf').resolve())])
def result(scores):
    rows = []
    for i, score in enumerate(scores):
        y = 100+i*100
        rows.append([[[95,y],[700,y],[700,y+65],[95,y+65]], f'校对行 {i+1}', score])
    return {'boxes': rows, 'text':'\n'.join(r[1] for r in rows), 'seconds':0.1}
scores = [0.88, 0.90, 0.97, 0.75]
w.on_result(0, result(scores))
w.on_result(1, result([0.99, 0.98]))
w.on_result(2, result([0.96, 0.89]))
w.files.setCurrentRow(0)
assert '低于 90 分：2 行' in w.review_count.text()
assert w.table.item(0, 0).background().color().name() == '#fff0ce'
assert w.table.item(1, 0).background().color().name() == '#ffffff', 'Equal threshold is excluded'
w.low_only.setChecked(True)
visible = lambda: [i for i in range(w.table.rowCount()) if not w.table.isRowHidden(i)]
assert visible() == [0, 3]
assert w.current_line == 0
next_button = next(b for b in w.findChildren(QPushButton) if b.text() == '↓ 下一行')
prev_button = next(b for b in w.findChildren(QPushButton) if b.text() == '↑ 上一行')
QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
assert w.current_line == 3
QTest.mouseClick(prev_button, Qt.MouseButton.LeftButton)
assert w.current_line == 0
w.pick_line(2)
assert w.current_line == 0, 'Hidden high-score source click cannot select an invisible row'
w.table.item(0, 2).setText('低分行已修改')
assert '低分行已修改' in w.editor.toPlainText()
assert '校对行 2' in w.editor.toPlainText() and '校对行 3' in w.editor.toPlainText()
w.copy_text()
assert app.clipboard().text() == w.entries[0]['text']

# Editing the threshold immediately changes counts, highlights and selection.
w.score_threshold.setValue(80.0)
assert visible() == [3] and w.current_line == 3
assert '低于 80 分：1 行' in w.review_count.text()
w.score_threshold.setValue(0.0)
assert visible() == [] and w.current_line == -1
assert '没有符合' in w.crop.text()
w.score_threshold.setValue(100.0)
assert visible() == [0, 1, 2, 3]
w.score_threshold.setValue(90.1)
assert visible() == [0, 1, 3], 'One decimal score adjustment works'
w.score_threshold.setValue(90.0)
w.pick_line(3)
QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
assert w.files.currentRow() == 2 and w.current_line == 1, 'Skip completed pages without eligible rows'
QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
assert w.files.currentRow() == 2 and '没有后续' in w.status.text()

# A pending page is recognized on navigation and then filtered at the same threshold.
w.entries[1].update(state='待识别', lines=[], boxes=[], text='')
w.files.setCurrentRow(0)
w.pick_line(3)
QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
assert w.files.currentRow() == 1 and w.worker.isRunning()
loop = QEventLoop()
w.worker.finished.connect(loop.quit)
QTimer.singleShot(120000, loop.quit)
loop.exec()
app.processEvents()
assert not w.worker.isRunning() and w.entries[1]['state'].startswith('已完成')
assert all(w.entries[1]['lines'][i]['confidence'] < 0.9 for i in visible())

# Added text has no OCR score and remains accessible for correction.
w.files.setCurrentRow(0)
w.editor.setPlainText(w.editor.toPlainText()+'\n人工新增文字')
assert 4 in visible() and '新增无分数：1 行' in w.review_count.text()
project = Path('work/pdf-test/score-filter.inkocr').resolve()
QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(project), '')
assert w.save_project()
saved = json.loads(project.read_text(encoding='utf-8'))
assert saved['settings']['score_threshold'] == 90 and saved['settings']['low_only'] is True
other = Window()
assert other.load_project(str(project))
assert other.low_only.isChecked() and other.score_threshold.value() == 90
assert other.entries[0]['text'] == w.entries[0]['text']
other.close()

# Export includes every line, even when the correction table is filtered.
target = Path('work/pdf-test/score-export.txt').resolve()
QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(target), '')
w.export_current()
assert target.read_text(encoding='utf-8-sig') == w.entries[0]['text']
w.low_only.setChecked(False)
assert visible() == [0,1,2,3,4]
w.low_only.setChecked(True)
w.save_project(automatic=True)
assert not errors, errors
w.grab().save('outputs/分数筛选校对预览.png')
w.close()
print('PASS: adjustable score cutoff, strict threshold boundary, live row counts/colors, filter navigation/cross-page OCR, unchanged full export, unknown-score lines and saved settings')
