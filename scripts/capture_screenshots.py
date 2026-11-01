"""Capture the real application with synthetic book pages, never user documents."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtTest import QTest
from app import Window, configure_fonts, CorrectionLineEdit

ROOT = Path(__file__).resolve().parents[1]

def main():
    output = ROOT/'docs/screenshots'
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    configure_fonts(app)
    window = Window()
    window.resize(1440, 940)
    window.show()
    window.add_files([str(ROOT/'examples/scanned-book-sample.pdf')])
    loop = QEventLoop()
    window.worker.finished.connect(loop.quit)
    window.start()
    QTimer.singleShot(180000, loop.quit)
    loop.exec()
    app.processEvents()
    if window.worker.isRunning() or not all(e['state'].startswith('已完成') for e in window.entries):
        raise RuntimeError('Screenshot sample OCR did not complete successfully')
    def settle():
        app.processEvents()
        app.processEvents()
        QTest.qWait(60)
    with tempfile.TemporaryDirectory(prefix='ink-ocr-demo-') as folder:
        project = Path(folder)/'示例电子书.inkocr'
        QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(project), '')
        window.save_project()
        def capture(name):
            window.save_project(automatic=True)
            window.status.setText('自制中英混排示例 · OCR、繁转简和校对均在本机处理')
            settle()
            if not window.grab().save(str(output/name)):
                raise RuntimeError('Failed to save '+str(name))
        window.pick_line(4)
        capture('horizontal.png')
        window.comparison_mode.setCurrentIndex(1)
        window.pick_line(4)
        capture('vertical.png')
        window.comparison_mode.setCurrentIndex(0)
        window.score_threshold.setValue(98.0)
        window.low_only.setChecked(True)
        settle()
        eligible = window.review_indices(window.entries[window.files.currentRow()])
        if eligible: window.pick_line(eligible[0])
        capture('score-filter.png')
        window.low_only.setChecked(False)
        window.score_threshold.setValue(90)
        window.comparison_mode.setCurrentIndex(1)
        window.pick_line(4)
        window.edit_selected()
        settle()
        editor = QApplication.focusWidget()
        if not isinstance(editor, CorrectionLineEdit) or editor.cursorPosition() != 0:
            raise RuntimeError('Keyboard editing preview was not ready')
        window.status.setText('Enter 已进入编辑，光标在文字最前面 · 再按 Enter 确认并返回行选择')
        window.grab().save(str(output/'keyboard-edit.png'))
        QTest.keyClick(editor, Qt.Key.Key_Return)
        settle()
        window.reorder_line(0, 2)
        window.pick_line(2)
        capture('row-order.png')
        window.undo_page()
        window.engine_combo.setCurrentText('Tesseract')
        window.page_snapshot()
        window.start(True, force=True)
        loop.exec()
        app.processEvents()
        if window.worker.isRunning() or window.entries[0].get('ocr_engine') != 'Tesseract':
            raise RuntimeError('Tesseract screenshot recognition failed')
        window.pick_line(0)
        capture('tesseract.png')
        window.save_project(automatic=True)
        window.close()
    print('Captured horizontal, vertical, low-score and keyboard-edit screenshots')

if __name__ == '__main__': main()
