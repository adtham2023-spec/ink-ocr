import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app import Window, configure_fonts, CorrectionLineEdit

app = QApplication([])
configure_fonts(app)
QMessageBox.question = lambda *args, **kwargs: QMessageBox.StandardButton.Discard
w = Window()
w.show()
w.comparison_mode.setCurrentIndex(1)
assert not w.dirty, 'Choosing a layout without a document must not create unsavable changes'
w.comparison_mode.setCurrentIndex(0)
w.add_files([str(Path('outputs/中英文测试图片.png').resolve())])
sample = json.loads(Path('work/packaged-offline.json').read_text(encoding='utf-8'))
w.on_result(0, sample)
def settle():
    app.processEvents()
    app.processEvents()
    app.processEvents()
w.pick_line(4)
settle()
assert w.comparison_mode.currentIndex() == 0
assert w.crop.parentWidget() == w.source_panel
rect = w.table.visualRect(w.table.model().index(4, 2))
assert abs(w.crop.mapToGlobal(w.crop.rect().center()).y()-w.table.viewport().mapToGlobal(rect.center()).y()) <= 1
text_before = w.entries[0]['text']
w.comparison_mode.setCurrentIndex(1)
settle()
assert w.vertical_original.isVisible() and w.crop.isVisible()
assert w.crop.parentWidget() == w.vertical_original
assert w.crop.mapToGlobal(w.crop.rect().bottomLeft()).y() < w.table.mapToGlobal(w.table.rect().topLeft()).y()
assert not w.crop.pixmap().isNull()
assert w.entries[0]['text'] == text_before, 'Layout change must not edit recognized text'
w.pick_line(0)
QTest.keyClick(w.table, Qt.Key.Key_Down)
assert w.current_line == 1
QTest.keyClick(w.table, Qt.Key.Key_Return)
settle()
edit = QApplication.focusWidget()
assert isinstance(edit, CorrectionLineEdit) and edit.cursorPosition() == 0
QTest.keyClicks(edit, 'Checked ')
QTest.keyClick(edit, Qt.Key.Key_Return)
settle()
assert w.entries[0]['lines'][1]['text'].startswith('Checked ') and w.table.hasFocus()
w.resize(1100, 740)
settle()
assert w.crop.isVisible() and w.vertical_original.width() > 100
w.tabs.setCurrentIndex(1)
settle()
assert not w.vertical_original.isVisible()
w.tabs.setCurrentIndex(0)
settle()
assert w.vertical_original.isVisible()
w.score_threshold.setValue(0)
w.low_only.setChecked(True)
settle()
assert not w.vertical_original.isVisible()
w.low_only.setChecked(False)
w.pick_line(4)
settle()
project = Path('work/pdf-test/comparison-modes.inkocr').resolve()
QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(project), '')
assert w.save_project()
other = Window()
other.show()
assert other.load_project(str(project))
settle()
assert other.comparison_mode.currentIndex() == 1 and other.vertical_original.isVisible()
assert other.entries[0]['text'] == w.entries[0]['text']
other.close()
w.resize(1450, 940)
settle()
w.grab().save('outputs/上下对照界面预览.png')
for _ in range(3):
    w.comparison_mode.setCurrentIndex(0)
    settle()
    assert w.crop.parentWidget() == w.source_panel and not w.vertical_original.isVisible()
    rect = w.table.visualRect(w.table.model().index(w.current_line, 2))
    assert abs(w.crop.mapToGlobal(w.crop.rect().center()).y()-w.table.viewport().mapToGlobal(rect.center()).y()) <= 1
    w.comparison_mode.setCurrentIndex(1)
    settle()
    assert w.vertical_original_layout.count() == 2
w.comparison_mode.setCurrentIndex(0)
w.save_project(automatic=True)
w.close()
print('PASS: horizontal/vertical switching, source placement, text retention, keyboard editing, resize/filter/tab behavior, saved orientation and repeated reparenting')
