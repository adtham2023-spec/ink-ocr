import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import json
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from app import Window, configure_fonts, remap_lines

app = QApplication([])
QMessageBox.question = lambda *args, **kwargs: QMessageBox.StandardButton.Discard
configure_fonts(app)
w = Window()
w.show()
image = str(Path('outputs/中英文测试图片.png').resolve())
w.add_files([image])
result = json.loads(Path('work/packaged-offline.json').read_text(encoding='utf-8'))
w.on_result(0, result)
app.processEvents()
assert w.table.rowCount() == len(result['boxes'])
# Right side selection highlights left side and creates a magnified original crop.
w.pick_line(4)
assert w.preview.selected == 4 and not w.crop.pixmap().isNull()
assert '012' in w.table.item(4, 2).text()
w.table.item(4, 2).setText('联系电话：012-345 6789（已核对）')
assert w.entries[0]['text'] == w.editor.toPlainText()
assert '（已核对）' in w.editor.toPlainText()
assert w.entries[0]['lines'][4]['original'] != w.entries[0]['lines'][4]['text']
# Click a real polygon on the original image, including when boxes are hidden.
w.box_check.setChecked(False)
box = w.entries[0]['lines'][2]['box']
point = QPointF(sum(p[0] for p in box)/4, sum(p[1] for p in box)/4)
QTest.mouseClick(w.preview.viewport(), Qt.MouseButton.LeftButton, pos=w.preview.mapFromScene(point))
assert w.table.currentRow() == 2 and w.current_line == 2
# Full text editing retains one-to-one links, and never jumps tabs.
w.tabs.setCurrentIndex(1)
w.editor.setPlainText(w.editor.toPlainText().replace('Mr.Zhang', 'Mr. Zhang'))
assert w.tabs.currentIndex() == 1
assert w.entries[0]['lines'][3]['box'] is not None
before = w.editor.toPlainText()
w.editor.setPlainText(before + '\n手动备注：已完成核对')
assert w.entries[0]['lines'][-1]['box'] is None
w.pick_line(w.table.rowCount()-1)
assert '没有对应' in w.crop.text()
# Export is corrected text, with a Chinese Windows-readable UTF-8 BOM.
target = Path('work/corrected-export.txt').resolve()
QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(target), '文本文件 (*.txt)')
w.export_current()
assert target.read_text(encoding='utf-8-sig') == w.entries[0]['text']
w.copy_text()
assert app.clipboard().text() == w.entries[0]['text']
# Uncertain mappings are removed when paragraphs are merged.
records = w.entries[0]['lines'][:2]
merged = remap_lines(records, 'merged paragraph')
assert len(merged) == 1 and merged[0]['box'] is None
# Image switching preserves edits.
other = Path('work/second-sample.png').resolve()
other.write_bytes(Path(image).read_bytes())
w.add_files([str(other)])
w.files.setCurrentRow(1)
w.files.setCurrentRow(0)
assert '（已核对）' in w.editor.toPlainText()
w.pick_line(4)
w.grab().save('outputs/纠错界面预览.png')
w.close()
print('PASS: two-way click mapping, corrected text persistence, original crop, full-text mapping, export, clipboard, file switching')
