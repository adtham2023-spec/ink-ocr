import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox, QSplitter
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from app import Window, configure_fonts

app = QApplication([])
configure_fonts(app)
QMessageBox.question = lambda *args, **kwargs: QMessageBox.StandardButton.Discard
class TrackedWindow(Window):
    def __init__(self):
        self.alignment_calls = 0
        super().__init__()
    def align_crop(self):
        self.alignment_calls += 1
        super().align_crop()
w = TrackedWindow()
w.show()
w.add_files([str(Path('outputs/中英文测试图片.png').resolve())])
sample = json.loads(Path('work/packaged-offline.json').read_text(encoding='utf-8'))
# Many rows force scrolling, including lines near the first and last visible edges.
result = dict(sample)
result['boxes'] = sample['boxes'] * 8
result['text'] = '\n'.join(row[1] for row in result['boxes'])
w.on_result(0, result)
app.processEvents()
def settle():
    app.processEvents()
    app.processEvents()
def check_alignment(row):
    w.pick_line(row)
    settle()
    assert w.crop.isVisible(), f'Original crop must be visible for selected row {row}'
    rect = w.table.visualRect(w.table.model().index(row, 2))
    source_y = w.crop.mapToGlobal(w.crop.rect().center()).y()
    text_y = w.table.viewport().mapToGlobal(rect.center()).y()
    assert abs(source_y-text_y) <= 1, (row, source_y, text_y)
    assert not w.crop.pixmap().isNull()
    assert w.crop.parentWidget() == w.source_panel
    assert w.crop.geometry().left() >= 0 and w.crop.geometry().right() < w.source_panel.width()
    assert w.crop.geometry().top() >= 0 and w.crop.geometry().bottom() < w.source_panel.height()

for row in (0, 4, 17, 35, w.table.rowCount()-1): check_alignment(row)
settle()
idle_before = w.alignment_calls
QTest.qWait(120)
assert w.alignment_calls-idle_before < 4, 'Preview must not continuously relayout while idle'
# Scroll the selection away: the original strip must hide instead of displaying
# next to a different row, then return to the same row when it is scrolled back.
w.table.verticalScrollBar().setValue(0)
settle()
assert not w.crop.isVisible()
w.table.scrollToItem(w.table.item(w.current_line, 2))
settle()
assert w.crop.isVisible()
check_alignment(w.current_line)
# Resizing the application and dragging panel widths must preserve the eye line.
w.resize(1100, 740)
settle()
check_alignment(26)
split = w.findChild(QSplitter)
split.setSizes([190, 350, 520])
settle()
check_alignment(5)
w.resize(1500, 960)
settle()
check_alignment(40)
# Filtering and changing tabs must not leave a stale floating original.
w.score_threshold.setValue(98.0)
w.low_only.setChecked(True)
settle()
eligible = w.review_indices(w.entries[0])
assert eligible
check_alignment(eligible[-1])
w.tabs.setCurrentIndex(1)
settle()
assert not w.crop.isVisible() and not w.crop_title.isVisible()
w.tabs.setCurrentIndex(0)
settle()
assert w.crop.isVisible()
w.score_threshold.setValue(0)
settle()
assert w.current_line == -1 and not w.crop.isVisible()
# Use actual OCR geometry for the delivered screenshot, not repeated test rows.
w.low_only.setChecked(False)
w.score_threshold.setValue(90)
w.on_result(0, sample)
w.pick_line(4)
settle()
w.grab().save('outputs/同行对照界面预览.png')
w.close()
print('PASS: crop/result horizontal alignment within 1px, scrolling, split/resize, filter/tab visibility and original preview mapping')
