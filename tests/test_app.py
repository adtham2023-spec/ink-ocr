import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage
from app import Window, configure_fonts

app = QApplication([])
QMessageBox.question = lambda *args, **kwargs: QMessageBox.StandardButton.Discard
configure_fonts(app)
w = Window()
w.show()
image = str(Path('outputs/中英文测试图片.png').resolve())
w.add_files([image, image])
assert len(w.entries) == 1, 'Duplicate files must be ignored'
w.start()
loop = QEventLoop()
w.worker.finished.connect(loop.quit)
QTimer.singleShot(120000, loop.quit)
loop.exec()
assert not w.worker.isRunning(), 'OCR timed out'
app.processEvents()
text = w.editor.toPlainText()
assert 'Zhang' in text and '1,280.50' in text and '中文' in text, text
w.box_check.setChecked(True)
app.processEvents()
w.grab().save('outputs/界面预览.png')
w.editor.setPlainText('编辑后的文字 Edited text')
w.copy_text()
assert app.clipboard().text() == '编辑后的文字 Edited text'
assert w.entries[0]['text'] == '编辑后的文字 Edited text'
w.clear()
assert len(w.entries) == 0 and not w.editor.toPlainText()
app.clipboard().setImage(QImage(image))
w.paste()
assert len(w.entries) == 1 and Path(w.entries[0]['path']).exists()
bad = Path('work/invalid.png')
bad.write_bytes(b'not an image')
w.add_files([str(bad.resolve())])
w.start()
loop.exec()
app.processEvents()
assert w.entries[1]['state'].startswith('失败'), w.entries[1]
assert w.run_btn.isEnabled()
w.close()
print('PASS: bilingual OCR, queue, duplicates, annotations, edits, clipboard, clear, invalid-file handling')
