import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox, QAbstractItemView, QLineEdit
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from app import Window, configure_fonts, CorrectionLineEdit

app = QApplication([])
configure_fonts(app)
QMessageBox.question = lambda *args, **kwargs: QMessageBox.StandardButton.Discard
w = Window()
w.show()
w.add_files([str(Path('work/pdf-test/扫描书样本.pdf').resolve())])
def sample(scores):
    rows = [[[[90,100+i*85],[900,100+i*85],[900,160+i*85],[90,160+i*85]],
             f'Original line {i+1} 中文', score] for i, score in enumerate(scores)]
    return {'text':'\n'.join(r[1] for r in rows), 'boxes':rows, 'seconds':0.1}
w.on_result(0, sample([0.80,0.99,0.85]))
w.on_result(1, sample([0.80,0.99,0.85]))
w.on_result(2, sample([0.80,0.99,0.85]))
def settle():
    app.processEvents()
    app.processEvents()
w.pick_line(0)
settle()
assert w.table.hasFocus()
QTest.keyClick(w.table, Qt.Key.Key_Down)
assert w.current_line == 1
QTest.keyClick(w.table, Qt.Key.Key_Up)
assert w.current_line == 0
before = w.entries[0]['lines'][0]['text']
QTest.keyClick(w.table, Qt.Key.Key_Return)
settle()
editor = QApplication.focusWidget()
assert isinstance(editor, CorrectionLineEdit), type(editor)
assert editor.cursorPosition() == 0 and not editor.hasSelectedText()
QTest.keyClicks(editor, 'Corrected: ')
assert editor.text() == 'Corrected: '+before, 'Typing must insert at front, not replace whole line'
QTest.keyClick(editor, Qt.Key.Key_Down)
assert w.current_line == 0 and w.table.state() == QAbstractItemView.State.EditingState
QTest.keyClick(editor, Qt.Key.Key_Return)
settle()
assert w.table.state() != QAbstractItemView.State.EditingState
assert w.table.hasFocus() and w.current_line == 0, 'Confirm must return to same row in review mode'
assert w.entries[0]['lines'][0]['text'] == 'Corrected: '+before
assert 'Corrected: ' in w.editor.toPlainText()
QTest.keyClick(w.table, Qt.Key.Key_Down)
assert w.current_line == 1
QTest.keyClick(w.table, Qt.Key.Key_Enter)
settle()
editor = QApplication.focusWidget()
assert isinstance(editor, CorrectionLineEdit) and editor.cursorPosition() == 0
before = editor.text()
# Chinese IME preedit Enter must not accidentally commit/close the whole row.
preedit = QInputMethodEvent('中文候选', [])
QApplication.sendEvent(editor, preedit)
assert editor.composing
QTest.keyClick(editor, Qt.Key.Key_Return)
assert w.table.state() == QAbstractItemView.State.EditingState
commit = QInputMethodEvent()
commit.setCommitString('校正')
QApplication.sendEvent(editor, commit)
assert not editor.composing and editor.text().startswith('校正')
QTest.keyClick(editor, Qt.Key.Key_Enter)
settle()
assert w.table.hasFocus() and w.current_line == 1
assert w.entries[0]['lines'][1]['text'] == '校正'+before
# Escape discards only the in-progress edit.
QTest.keyClick(w.table, Qt.Key.Key_Return)
settle()
editor = QApplication.focusWidget()
QTest.keyClicks(editor, 'discard me')
QTest.keyClick(editor, Qt.Key.Key_Escape)
settle()
assert w.entries[0]['lines'][1]['text'] == '校正'+before and w.table.hasFocus()
# Keyboard navigation follows score filtering and crosses page boundaries.
w.low_only.setChecked(True)
w.pick_line(0)
QTest.keyClick(w.table, Qt.Key.Key_Down)
assert w.current_line == 2
QTest.keyClick(w.table, Qt.Key.Key_Down)
assert w.files.currentRow() == 1 and w.current_line == 0 and w.table.hasFocus()
# Focusing a threshold control must keep its own arrow-key behavior.
w.score_threshold.setFocus()
settle()
QTest.keyClick(w.score_threshold, Qt.Key.Key_Up)
assert w.score_threshold.value() == 91 and w.score_threshold.hasFocus()
# Full text remains a normal multiline editor, with no correction shortcut hijack.
w.tabs.setCurrentIndex(1)
w.editor.setFocus()
settle()
cursor = w.editor.textCursor()
cursor.movePosition(cursor.MoveOperation.End)
w.editor.setTextCursor(cursor)
QTest.keyClick(w.editor, Qt.Key.Key_Return)
assert w.editor.toPlainText().endswith('\n') and w.editor.hasFocus()
# Mouse/button entry uses the same cursor-at-front behavior.
w.tabs.setCurrentIndex(0)
w.pick_line(0)
w.edit_selected()
settle()
editor = QApplication.focusWidget()
assert isinstance(editor, CorrectionLineEdit) and editor.cursorPosition() == 0
QTest.keyClick(editor, Qt.Key.Key_Return)
settle()
cell = w.table.visualRect(w.table.model().index(w.current_line, 2))
QTest.mouseClick(w.table.viewport(), Qt.MouseButton.LeftButton, pos=cell.center())
QTest.mouseDClick(w.table.viewport(), Qt.MouseButton.LeftButton, pos=cell.center())
settle()
editor = QApplication.focusWidget()
assert isinstance(editor, CorrectionLineEdit) and editor.cursorPosition() == 0 and not editor.hasSelectedText(), (type(editor), editor.cursorPosition() if isinstance(editor,QLineEdit) else None, editor.selectedText() if isinstance(editor,QLineEdit) else None)
QTest.keyClick(editor, Qt.Key.Key_Return)
settle()
w.close()
print('PASS: arrow row navigation, Enter/start-of-text editing, Enter commit and focus return, keypad Enter, Chinese IME preedit, Escape, low-score/page navigation and non-review controls')
