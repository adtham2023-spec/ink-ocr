"""墨识 / Ink OCR: fully local bilingual image OCR desktop app."""
import os
os.environ['QT_API'] = 'pyside6'
import sys
import json
import time
import tempfile
import threading
import base64
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPointF, QPoint, QEvent
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QKeySequence, QShortcut, QFontDatabase, QFont, QIcon, QPolygonF, QBrush
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QFileDialog, QListWidget, QListWidgetItem,
    QPlainTextEdit, QSplitter, QCheckBox, QProgressBar, QMessageBox, QFrame,
    QGraphicsView, QGraphicsScene, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSpinBox, QDoubleSpinBox,
    QStyledItemDelegate, QLineEdit, QComboBox, QSizePolicy)

EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}
PDF_LOCK = threading.RLock()

@lru_cache(maxsize=1)
def simplified_converter():
    from opencc import OpenCC
    return OpenCC('t2s')

def to_simplified(text):
    return simplified_converter().convert(text)

def entry_label(entry):
    name = Path(entry['path']).name
    return f'{name} · 第 {entry["page"]+1} 页' if entry.get('page') is not None else name

def source_key(entry):
    return (os.path.normcase(entry['path']), entry.get('page'))

def read_source(source):
    if not isinstance(source, dict): return read_image(source)
    if source.get('page') is None: return read_image(source['path'])
    import pypdfium2 as pdfium
    # PDFium cannot be called concurrently, even for different documents.
    with PDF_LOCK, pdfium.PdfDocument(source['path']) as doc:
        page = doc[source['page']]
        try:
            w, h = page.get_size()
            scale = min(3.0, 3200/max(w, h))
            bitmap = page.render(scale=scale)
            try:
                return np.asarray(bitmap.to_pil().convert('RGB'))[:, :, ::-1].copy()
            finally: bitmap.close()
        finally: page.close()

def source_ref(entry):
    return {'path': entry['path'], 'page': entry.get('page')}

def configure_fonts(app):
    # Explicit font loading also works on machines with font fallback disabled.
    for name in ('msyh.ttc', 'msyhbd.ttc'):
        path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
        if path.exists(): QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('Microsoft YaHei', 10))

def read_image(path):
    with Image.open(path) as im:
        return np.asarray(ImageOps.exif_transpose(im).convert('RGB'))[:, :, ::-1].copy()

def make_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=4, inter_op_num_threads=1,
                    det_limit_side_len=1280, det_limit_type='max', max_side_len=3600)

def recognize(engine, path):
    start = time.perf_counter()
    rows, _ = engine(read_source(path))
    rows = rows or []
    return {'text': '\n'.join(r[1] for r in rows),
            'boxes': [[np.asarray(r[0]).tolist(), r[1], float(r[2])] for r in rows],
            'seconds': round(time.perf_counter() - start, 2)}

class OCRWorker(QThread):
    result = Signal(int, object)
    failure = Signal(int, str)
    progress = Signal(int, int)
    def __init__(self):
        super().__init__()
        self.engine = None
        self.jobs = []
    def run(self):
        try:
            if self.engine is None:
                self.engine = make_engine()
        except Exception as exc:
            for index, _ in self.jobs:
                self.failure.emit(index, '模型初始化失败：' + str(exc))
            return
        for count, (index, path) in enumerate(self.jobs, 1):
            if self.isInterruptionRequested(): break
            try:
                self.result.emit(index, recognize(self.engine, path))
            except Exception as exc:
                self.failure.emit(index, str(exc))
            self.progress.emit(count, len(self.jobs))

def remap_lines(old, text):
    """Preserve coordinates for unchanged and one-to-one edited text lines.

    Inserted/restructured text deliberately gets no coordinates rather than a
    misleading link to an unrelated image region.
    """
    new = text.split('\n') if text else []
    result = []
    for tag, a, b, c, d in SequenceMatcher(None, [r['text'] for r in old], new, autojunk=False).get_opcodes():
        if tag == 'equal': result.extend(dict(r) for r in old[a:b])
        elif tag in ('replace', 'insert'):
            for offset, value in enumerate(new[c:d]):
                record = dict(old[a+offset]) if tag == 'replace' and b-a == d-c else {
                    'box': None, 'confidence': None, 'original': None}
                record['text'] = value
                result.append(record)
    return result

class Preview(QGraphicsView):
    lineClicked = Signal(int)
    def __init__(self):
        super().__init__()
        self.scene_data = QGraphicsScene(self)
        self.setScene(self.scene_data)
        self.setMinimumSize(280, 260)
        self.original = QPixmap()
        self.regions = []
        self.selected = -1
        self.show_boxes = True
        self.auto_fit = True
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setStyleSheet('background:#f1f3f0; border:1px solid #e1e5df; border-radius:12px;')
        self.clear_document()
    def clear_document(self):
        self.scene_data.clear()
        self.original = QPixmap()
        self.regions = []
        self.scene_data.addText('导入图片后，点击文字框对照纠错')
    def set_document(self, pix, lines, show_boxes, reset=False):
        self.original = pix
        self.scene_data.clear()
        self.scene_data.addPixmap(pix)
        self.scene_data.setSceneRect(0, 0, pix.width(), pix.height())
        self.regions = []
        self.show_boxes = show_boxes
        for i, line in enumerate(lines):
            if line['box'] is None: continue
            polygon = QPolygonF([QPointF(float(x), float(y)) for x, y in line['box']])
            item = self.scene_data.addPolygon(polygon)
            item.setZValue(1)
            self.regions.append((i, item))
        self.highlight(self.selected, center=False)
        if reset:
            self.auto_fit = True
            self.refresh()
    def highlight(self, index, center=True):
        self.selected = index
        for i, item in self.regions:
            selected = i == index
            pen = QPen(QColor('#df8d24' if selected else '#438c62'), 2 if selected else 1)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setBrush(QBrush(QColor(255, 179, 64, 65)) if selected else QBrush(Qt.BrushStyle.NoBrush))
            item.setVisible(self.show_boxes or selected)
            if selected and center: self.ensureVisible(item, 35, 35)
    def refresh(self):
        if not self.original.isNull() and self.auto_fit:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    def fit_image(self):
        self.auto_fit = True
        self.refresh()
    def wheelEvent(self, event):
        if self.original.isNull(): return
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        scale = self.transform().m11() * factor
        if 0.03 < scale < 10:
            self.auto_fit = False
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.scale(factor, factor)
        event.accept()
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            hits = [(item.boundingRect().width()*item.boundingRect().height(), i)
                    for i, item in self.regions if item.polygon().containsPoint(point, Qt.FillRule.OddEvenFill)]
            if hits: self.lineClicked.emit(min(hits)[1])
        super().mousePressEvent(event)
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

class ReviewTable(QTableWidget):
    navigate = Signal(int)
    editRequested = Signal()
    def keyPressEvent(self, event):
        if self.state() != QAbstractItemView.State.EditingState and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self.navigate.emit(-1 if event.key() == Qt.Key.Key_Up else 1)
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not event.isAutoRepeat(): self.editRequested.emit()
                event.accept()
                return
        super().keyPressEvent(event)

class CorrectionLineEdit(QLineEdit):
    def __init__(self, parent):
        super().__init__(parent)
        self.composing = False
        self.initial_focus = True
    def inputMethodEvent(self, event):
        self.composing = bool(event.preeditString())
        super().inputMethodEvent(event)
    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self.initial_focus:
            self.deselect()
            self.setCursorPosition(0)
            self.initial_focus = False

class CorrectionDelegate(QStyledItemDelegate):
    reviewFinished = Signal(bool)
    def createEditor(self, parent, option, index):
        return CorrectionLineEdit(parent)
    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        editor.deselect()
        editor.setCursorPosition(0)
    def eventFilter(self, editor, event):
        if isinstance(editor, CorrectionLineEdit) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Candidate confirmation belongs to the Chinese input method;
                # it must not accidentally finish the entire correction.
                if not editor.composing and not event.isAutoRepeat():
                    self.commitData.emit(editor)
                    self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                    self.reviewFinished.emit(True)
                event.accept()
                return True
            if key == Qt.Key.Key_Escape:
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.RevertModelCache)
                self.reviewFinished.emit(False)
                event.accept()
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                # Keep the row stable while editing a single line.
                event.accept()
                return True
        return super().eventFilter(editor, event)

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('墨识 Ink OCR 8 · 水平 / 上下对照')
        self.resize(1380, 900)
        self.setMinimumSize(940, 620)
        self.setAcceptDrops(True)
        self.entries = []
        self.loading = False
        self.line_loading = False
        self.current_line = -1
        self.pending_navigation = None
        self.preview_path = None
        self.source_pix = QPixmap()
        self.crop_source = QPixmap()
        self.crop_render_key = None
        self.crop_update_timer = QTimer(self)
        self.crop_update_timer.setSingleShot(True)
        self.crop_update_timer.timeout.connect(self.align_crop)
        self.project_file = None
        self.dirty = False
        self.saving = False
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(1000)
        self.autosave.timeout.connect(lambda: self.save_project(automatic=True))
        self.temp = tempfile.TemporaryDirectory(prefix='ink-ocr-')
        self.worker = OCRWorker()
        self.worker.result.connect(self.on_result)
        self.worker.failure.connect(self.on_error)
        self.worker.progress.connect(lambda n, total: self.bar.setValue(n))
        self.worker.finished.connect(self.done)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(26, 24, 26, 18)
        layout.setSpacing(18)
        header = QHBoxLayout()
        title = QLabel('墨识  <span style="color:#8c9689; font-size:18px; font-weight:400">INK OCR</span>')
        title.setStyleSheet('font-size:30px; font-weight:700;')
        header.addWidget(title)
        header.addStretch()
        badge = QLabel('●  本机处理 · 无需联网 · 无 API')
        badge.setStyleSheet('color:#447155; background:#e9f2e8; padding:9px 14px; border-radius:16px;')
        header.addWidget(badge)
        layout.addLayout(header)
        sub = QLabel('扫描电子书 PDF · 按页识别 · 左右对照纠错 · 保存校对进度')
        sub.setStyleSheet('color:#74806f; font-size:14px;')
        layout.addWidget(sub)
        toolbar = QHBoxLayout()
        self.add_btn = self.button('＋  导入 PDF / 图片', self.choose)
        self.paste_btn = self.button('粘贴图片', self.paste)
        self.current_btn = self.button('识别当前页', lambda: self.start(True))
        self.run_btn = self.button('识别全部', self.start, True)
        self.stop_btn = self.button('停止', self.stop)
        self.stop_btn.setEnabled(False)
        self.clear_btn = self.button('清空列表', self.clear)
        for btn in (self.add_btn, self.paste_btn, self.current_btn, self.run_btn, self.stop_btn, self.clear_btn):
            toolbar.addWidget(btn)
        toolbar.addStretch()
        self.box_check = QCheckBox('显示文字框')
        self.box_check.setChecked(True)
        self.box_check.toggled.connect(self.update_preview)
        toolbar.addWidget(self.box_check)
        layout.addLayout(toolbar)
        projectbar = QHBoxLayout()
        self.open_project_btn = self.button('打开进度', self.open_project)
        self.save_project_btn = self.button('保存进度  Ctrl+S', self.save_project)
        projectbar.addWidget(self.open_project_btn)
        projectbar.addWidget(self.save_project_btn)
        self.simplify_check = QCheckBox('识别后转简体')
        self.simplify_check.setChecked(True)
        self.simplify_check.setToolTip('只影响后续识别结果；原图和原始识别文字保留。')
        self.simplify_check.toggled.connect(self.mark_dirty)
        projectbar.addWidget(self.simplify_check)
        self.simplify_btn = self.button('当前页繁转简', self.simplify_current)
        projectbar.addWidget(self.simplify_btn)
        projectbar.addWidget(QLabel('对照方式'))
        self.comparison_mode = QComboBox()
        self.comparison_mode.addItems(['水平对照', '上下对照'])
        self.comparison_mode.setToolTip('水平：原文与选中行同高；上下：原文在识别列表上方。')
        projectbar.addWidget(self.comparison_mode)
        self.project_label = QLabel('尚未保存进度 · 首次保存后自动更新')
        self.project_label.setStyleSheet('color:#74806f;')
        projectbar.addWidget(self.project_label, 1)
        layout.addLayout(projectbar)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 12, 0)
        self.count_label = QLabel('页面队列 / 0')
        left_layout.addWidget(self.count_label)
        self.files = QListWidget()
        self.files.currentRowChanged.connect(self.select)
        self.files.setMinimumWidth(180)
        left_layout.addWidget(self.files)
        pagebar = QHBoxLayout()
        pagebar.addWidget(self.button('‹', lambda: self.move_page(-1)))
        self.page_spin = QSpinBox()
        self.page_spin.setRange(0, 0)
        self.page_spin.setPrefix('第 ')
        self.page_spin.setSuffix(' 页')
        self.page_spin.valueChanged.connect(lambda n: self.files.setCurrentRow(n-1) if n > 0 else None)
        pagebar.addWidget(self.page_spin, 1)
        pagebar.addWidget(self.button('›', lambda: self.move_page(1)))
        left_layout.addLayout(pagebar)
        hint = QLabel('支持多页扫描 PDF\n及 PNG / JPG / WEBP\n\n逐页读取，不一次加载整本书\n保存进度后可关闭再继续')
        hint.setStyleSheet('color:#899287; font-size:12px; padding:8px;')
        left_layout.addWidget(hint)
        split.addWidget(left)
        middle = QWidget()
        self.source_panel = middle
        ml = QVBoxLayout(middle)
        ml.setContentsMargins(6, 0, 12, 0)
        ph = QHBoxLayout()
        ph.addWidget(QLabel('原图 / 点击文字框定位'))
        ph.addStretch()
        ph.addWidget(self.button('适应窗口', lambda: self.preview.fit_image()))
        ml.addLayout(ph)
        self.preview = Preview()
        self.preview.lineClicked.connect(self.pick_line)
        ml.addWidget(self.preview, 1)
        # Keep the magnified source on the selected result's eye line rather
        # than in a fixed footer far below the correction text.
        self.crop = QLabel('点击右侧任意一行，查看原文细节', middle)
        self.crop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop.setFixedHeight(100)
        self.crop.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.crop.setStyleSheet('background:white; border:2px solid #d89537; border-radius:8px; color:#74806f; padding:6px;')
        self.crop.hide()
        self.crop_title = QLabel('选中行原文', middle)
        self.crop_title.setStyleSheet('background:#fff6e5; color:#925d19; padding:3px 8px; border-radius:5px; font-size:12px;')
        self.crop_title.hide()
        mhint = QLabel('滚轮缩放原图 · 按住拖动 · 对照方式可在上方切换')
        mhint.setStyleSheet('color:#74806f; font-size:12px;')
        ml.addWidget(mhint)
        self.info = QLabel('等待导入图片')
        self.info.setWordWrap(True)
        self.info.setStyleSheet('color:#74806f; font-size:12px;')
        ml.addWidget(self.info)
        split.addWidget(middle)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        rh = QHBoxLayout()
        rh.addWidget(QLabel('识别内容 / 点选对照，双击修改'))
        rh.addStretch()
        self.chars = QLabel('0 字符')
        rh.addWidget(self.chars)
        rl.addLayout(rh)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText('识别后的文字会出现在这里。\n\n结果可编辑，也可复制或导出。')
        self.editor.textChanged.connect(self.edited)
        self.tabs = QTabWidget()
        correction = QWidget()
        cl = QVBoxLayout(correction)
        cl.setContentsMargins(0, 10, 0, 0)
        filterbar = QHBoxLayout()
        filterbar.addWidget(QLabel('低分阈值'))
        self.score_threshold = QDoubleSpinBox()
        self.score_threshold.setRange(0.0, 100.0)
        self.score_threshold.setDecimals(1)
        self.score_threshold.setSingleStep(1.0)
        self.score_threshold.setSuffix(' 分')
        self.score_threshold.setValue(90.0)
        self.score_threshold.setToolTip('低于此分数的 OCR 行会标黄；等于阈值的行不计入低分。')
        filterbar.addWidget(self.score_threshold)
        self.low_only = QCheckBox('只校对低分行')
        self.low_only.setToolTip('筛选逐行列表和上一行/下一行；全文与导出仍保留全部文字。新增无分数行也会显示。')
        filterbar.addWidget(self.low_only)
        filterbar.addStretch()
        cl.addLayout(filterbar)
        self.review_count = QLabel('当前页：0 行，低分 0 行')
        self.review_count.setStyleSheet('color:#74806f; font-size:12px;')
        cl.addWidget(self.review_count)
        self.vertical_original = QWidget()
        self.vertical_original_layout = QVBoxLayout(self.vertical_original)
        self.vertical_original_layout.setContentsMargins(0, 0, 0, 0)
        self.vertical_original_layout.setSpacing(4)
        self.vertical_original.hide()
        cl.addWidget(self.vertical_original)
        self.table = ReviewTable(0, 3)
        self.correction_delegate = CorrectionDelegate(self.table)
        self.table.setItemDelegateForColumn(2, self.correction_delegate)
        self.table.navigate.connect(self.move_line)
        self.table.editRequested.connect(self.edit_selected)
        self.correction_delegate.reviewFinished.connect(self.finish_line_edit)
        self.table.setHorizontalHeaderLabels(['行', '分数', '识别文字（Enter 编辑）'])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(1, 68)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.currentCellChanged.connect(lambda row, col, oldrow, oldcol: self.line_selected(row))
        self.table.itemChanged.connect(self.line_edited)
        self.score_threshold.valueChanged.connect(self.review_settings_changed)
        self.low_only.toggled.connect(self.review_settings_changed)
        cl.addWidget(self.table, 1)
        keyboard_hint = QLabel('↑ / ↓ 切换行  ·  Enter 开始修改（光标在最前）  ·  再按 Enter 完成')
        keyboard_hint.setWordWrap(True)
        keyboard_hint.setStyleSheet('color:#74806f; font-size:12px;')
        cl.addWidget(keyboard_hint)
        self.line_note = QLabel('识别后可调整低分阈值，优先校对标黄的行。')
        self.line_note.setWordWrap(True)
        cl.addWidget(self.line_note)
        nav = QHBoxLayout()
        nav.addWidget(self.button('↑ 上一行', lambda: self.move_line(-1)))
        nav.addWidget(self.button('↓ 下一行', lambda: self.move_line(1)))
        nav.addWidget(self.button('编辑选中行  Enter', self.edit_selected))
        cl.addLayout(nav)
        self.tabs.addTab(correction, '逐行纠错')
        self.tabs.addTab(self.editor, '全文编辑')
        self.tabs.currentChanged.connect(self.schedule_crop_alignment)
        self.comparison_mode.currentIndexChanged.connect(self.change_comparison_layout)
        rl.addWidget(self.tabs)
        export = QHBoxLayout()
        export.addWidget(self.button('复制文字', self.copy_text))
        export.addWidget(self.button('导出当前 TXT', self.export_current))
        export.addWidget(self.button('导出全部 TXT', self.export_all))
        rl.addLayout(export)
        split.addWidget(right)
        split.setSizes([180, 560, 580])
        split.splitterMoved.connect(self.schedule_crop_alignment)
        self.table.verticalScrollBar().valueChanged.connect(self.schedule_crop_alignment)
        self.table.horizontalHeader().sectionResized.connect(self.schedule_crop_alignment)
        for watched in (self.source_panel, self.table, self.table.viewport(), self.preview):
            watched.installEventFilter(self)
        layout.addWidget(split, 1)
        self.bar = QProgressBar()
        self.bar.setMaximumHeight(6)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.status = QLabel('准备就绪  ·  模型已随程序内置，图片不会上传')
        self.status.setStyleSheet('font-size:12px; color:#74806f;')
        layout.addWidget(self.status)
        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.choose)
        QShortcut(QKeySequence('Ctrl+S'), self, activated=self.save_project)
        QShortcut(QKeySequence('Ctrl+V'), self, activated=self.paste, context=Qt.ShortcutContext.WindowShortcut)
        self.setStyleSheet('''
            QMainWindow { background:#fafbf8; }
            QWidget { font-family:"Microsoft YaHei"; color:#25382c; font-size:13px; }
            QPushButton { background:white; border:1px solid #dce3d9; border-radius:8px; padding:10px 15px; }
            QPushButton:hover { background:#edf3e9; border-color:#96b28b; }
            QPushButton:disabled { color:#adb5aa; background:#f0f2ed; }
            QPushButton[primary="true"] { background:#326647; color:white; border-color:#326647; font-weight:600; }
            QPushButton[primary="true"]:hover { background:#254f37; }
            QListWidget, QPlainTextEdit { background:white; border:1px solid #e0e6dc; border-radius:10px; padding:9px; }
            QListWidget::item { padding:12px 5px; border-radius:6px; }
            QListWidget::item:selected { background:#e9f2e4; color:#285237; }
            QPlainTextEdit { font-size:15px; selection-background-color:#c3ddba; }
            QProgressBar { border:0; background:#e3eadd; border-radius:3px; }
            QProgressBar::chunk { background:#538557; border-radius:3px; }
            QSplitter::handle { background:transparent; width:5px; }
            QTableWidget { background:white; border:1px solid #e0e6dc; border-radius:8px; gridline-color:#edf1e9; font-size:14px; selection-background-color:#dcebd4; selection-color:#203b2a; }
            QHeaderView::section { background:#edf3e9; padding:9px 4px; border:0; color:#476046; }
            QTabWidget::pane { border:0; }
            QTabBar::tab { padding:10px 18px; background:#f0f3ed; border-radius:6px; }
            QTabBar::tab:selected { background:#dcebd4; color:#285237; }
        ''')
    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            self.schedule_crop_alignment()
        return super().eventFilter(watched, event)
    def schedule_crop_alignment(self, *args):
        if not self.crop_update_timer.isActive(): self.crop_update_timer.start(0)
    def change_comparison_layout(self, index=None, persist=True):
        self.crop.hide()
        self.crop_title.hide()
        if self.comparison_mode.currentIndex() == 1:
            self.crop_title.setParent(self.vertical_original)
            self.crop.setParent(self.vertical_original)
            self.vertical_original_layout.addWidget(self.crop_title)
            self.vertical_original_layout.addWidget(self.crop)
            self.crop.setFixedHeight(100)
        else:
            self.vertical_original_layout.removeWidget(self.crop_title)
            self.vertical_original_layout.removeWidget(self.crop)
            self.crop_title.setParent(self.source_panel)
            self.crop.setParent(self.source_panel)
            self.vertical_original.hide()
        self.crop_render_key = None
        self.schedule_crop_alignment()
        if persist and self.entries: self.mark_dirty()
    def scroll_review_row(self, index):
        hint = (QAbstractItemView.ScrollHint.PositionAtTop if self.comparison_mode.currentIndex() == 1
                else QAbstractItemView.ScrollHint.EnsureVisible)
        self.table.scrollToItem(self.table.item(index, 2), hint)
    def align_crop(self):
        if not hasattr(self, 'table'): return
        row = self.current_line
        if (self.tabs.currentIndex() != 0 or row < 0 or row >= self.table.rowCount()
                or self.table.isRowHidden(row)):
            self.crop.hide()
            self.crop_title.hide()
            self.vertical_original.hide()
            return
        if self.comparison_mode.currentIndex() == 1:
            self.vertical_original.show()
            self.crop_title.setText(f'第 {row+1} 行原文 · 下方为识别内容')
            self.crop_title.show()
            self.crop.setFixedHeight(100)
            self.crop.show()
            width = max(100, self.vertical_original.width())
            key = (self.crop_source.cacheKey(), width, 100)
            if not self.crop_source.isNull() and key != self.crop_render_key:
                self.crop.setPixmap(self.crop_source.scaled(max(1, width-18), 82,
                    Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.crop_render_key = key
            return
        self.vertical_original.hide()
        rect = self.table.visualRect(self.table.model().index(row, 2))
        viewport = self.table.viewport().rect()
        # Never pin an off-screen selection to a misleading row at the edge.
        if not viewport.contains(QPoint(viewport.center().x(), rect.center().y())):
            self.crop.hide()
            self.crop_title.hide()
            return
        point = self.source_panel.mapFromGlobal(self.table.viewport().mapToGlobal(QPoint(0, rect.center().y())))
        width = max(100, self.preview.width()-16)
        space = max(12, min(point.y(), self.source_panel.height()-point.y()-1))
        height = min(100, 2*space)
        self.crop.setFixedHeight(height)
        self.crop.resize(width, height)
        self.crop.move(self.preview.x()+8, point.y()-(height-1)//2)
        if not self.crop_source.isNull():
            key = (self.crop_source.cacheKey(), width, height)
            if key != self.crop_render_key:
                self.crop.setPixmap(self.crop_source.scaled(max(1, width-18), max(1, height-18),
                    Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.crop_render_key = key
        caption = f'第 {row+1} 行原文 · 与右侧选中行对齐'
        if self.crop_title.text() != caption: self.crop_title.setText(caption)
        self.crop_title.adjustSize()
        self.crop_title.move(self.crop.x(), max(0, self.crop.y()-self.crop_title.height()-3))
        self.crop.show()
        self.crop.raise_()
        self.crop_title.show()
        self.crop_title.raise_()
    def button(self, text, callback, primary=False):
        btn = QPushButton(text)
        btn.setProperty('primary', primary)
        btn.clicked.connect(callback)
        return btn
    def choose(self):
        if self.worker.isRunning(): return
        paths, _ = QFileDialog.getOpenFileNames(self, '选择扫描 PDF 或图片', '', 'PDF 和图片 (*.pdf *.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)')
        self.add_files(paths)
    def add_files(self, paths):
        if self.worker.isRunning(): return
        existing = {source_key(e) for e in self.entries}
        for path in paths:
            path = str(Path(path).resolve())
            ext = Path(path).suffix.lower()
            if ext not in EXTENSIONS | {'.pdf'}: continue
            try:
                if ext == '.pdf':
                    import pypdfium2 as pdfium
                    with PDF_LOCK, pdfium.PdfDocument(path) as doc: pages = range(len(doc))
                else: pages = [None]
                stat = Path(path).stat()
                for page in pages:
                    entry = {'path':path, 'page':page, 'text':'', 'boxes':[], 'state':'待识别',
                             'source_size':stat.st_size, 'source_mtime':stat.st_mtime_ns}
                    if source_key(entry) in existing: continue
                    existing.add(source_key(entry))
                    self.entries.append(entry)
                    self.files.addItem(entry_label(entry) + '\n待识别')
            except Exception as exc:
                QMessageBox.warning(self, '无法导入文件', f'{Path(path).name}\n{exc}\n如 PDF 有密码，请先解锁后导入。')
        self.update_page_count()
        self.mark_dirty()
        if self.files.currentRow() < 0 and self.entries:
            self.files.setCurrentRow(0)
    def paste(self):
        if self.worker.isRunning(): return
        # Preserve normal text paste while editing the recognition result.
        clip = QApplication.clipboard()
        if clip.mimeData().hasImage():
            img = clip.image()
            if not img.isNull():
                path = str(Path(self.temp.name) / f'剪贴板_{time.time_ns()}.png')
                img.save(path)
                self.add_files([path])
        elif self.table.state() == QAbstractItemView.State.EditingState:
            focus = QApplication.focusWidget()
            if hasattr(focus, 'paste'): focus.paste()
        elif self.editor.hasFocus():
            self.editor.paste()
        elif clip.mimeData().hasUrls():
            self.add_files([u.toLocalFile() for u in clip.mimeData().urls() if u.isLocalFile()])
        else:
            self.status.setText('剪贴板中没有图片；可以先用 Win+Shift+S 截图。')
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.worker.isRunning(): event.acceptProposedAction()
    def dropEvent(self, event):
        self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()
    def select(self, row):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(row+1 if row >= 0 else 0)
        self.page_spin.blockSignals(False)
        self.loading = True
        self.editor.setPlainText(self.entries[row]['text'] if row >= 0 else '')
        self.loading = False
        self.current_line = -1
        self.refresh_lines()
        self.update_preview()
        if row >= 0:
            indices = self.review_indices(self.entries[row])
            if indices: self.pick_line(indices[0])
    def update_preview(self):
        row = self.files.currentRow()
        if row < 0:
            self.preview.clear_document()
            self.preview_path = None
            self.source_pix = QPixmap()
            self.crop_source = QPixmap()
            self.crop.clear()
            self.schedule_crop_alignment()
            self.info.setText('等待导入图片')
            return
        entry = self.entries[row]
        try:
            reset = self.preview_path != source_key(entry)
            if reset:
                arr = read_source(source_ref(entry))[:, :, ::-1].copy()
                h, w, _ = arr.shape
                self.source_pix = QPixmap.fromImage(QImage(arr.data, w, h, 3*w, QImage.Format.Format_RGB888).copy())
                self.preview_path = source_key(entry)
            w, h = self.source_pix.width(), self.source_pix.height()
            self.preview.set_document(self.source_pix, entry.get('lines', []), self.box_check.isChecked(), reset)
            self.preview.highlight(self.current_line, center=False)
            self.info.setText(f'{entry_label(entry)}  ·  {w} × {h}\n{entry["state"]}')
        except Exception as exc:
            self.preview.clear_document()
            self.preview_path = None
            self.source_pix = QPixmap()
            self.info.setText(str(exc))
    def edited(self):
        text = self.editor.toPlainText()
        self.chars.setText(f'{len(text)} 字符')
        row = self.files.currentRow()
        if row >= 0 and not self.loading:
            self.entries[row]['text'] = text
            self.entries[row]['lines'] = remap_lines(self.entries[row].get('lines', []), text)
            self.refresh_lines()
            self.update_preview()
            self.mark_dirty()
    def refresh_lines(self):
        self.line_loading = True
        row = self.files.currentRow()
        lines = self.entries[row].get('lines', []) if row >= 0 else []
        self.table.setRowCount(len(lines))
        for i, line in enumerate(lines):
            confidence = line['confidence']
            values = [str(i+1), f'{confidence*100:.2f}' if confidence is not None else '新增', line['text']]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col < 2: item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if confidence is not None and confidence < self.score_threshold.value()/100:
                    item.setBackground(QColor('#fff0ce'))
                if col == 2 and line['original'] is not None and line['text'] != line['original']:
                    item.setForeground(QColor('#327249'))
                self.table.setItem(i, col, item)
            self.table.setRowHeight(i, 39)
        self.line_loading = False
        self.apply_review_filter(select_first=self.current_line >= 0)
    def review_indices(self, entry):
        lines = entry.get('lines', [])
        if not self.low_only.isChecked(): return list(range(len(lines)))
        threshold = self.score_threshold.value()/100
        return [i for i, line in enumerate(lines)
                if line['confidence'] is None or line['confidence'] < threshold]
    def review_settings_changed(self, value=None):
        self.apply_review_filter()
        self.mark_dirty()
    def apply_review_filter(self, select_first=True):
        row = self.files.currentRow()
        entry = self.entries[row] if 0 <= row < len(self.entries) else {}
        lines = entry.get('lines', [])
        threshold = self.score_threshold.value()/100
        eligible = self.review_indices(entry)
        allowed = set(eligible)
        low_count = sum(line['confidence'] is not None and line['confidence'] < threshold for line in lines)
        unknown = sum(line['confidence'] is None for line in lines)
        self.review_count.setText(f'当前页：共 {len(lines)} 行 · 低于 {self.score_threshold.value():g} 分：{low_count} 行'
                                  + (f' · 新增无分数：{unknown} 行' if unknown else ''))
        self.line_loading = True
        for i, line in enumerate(lines):
            self.table.setRowHidden(i, i not in allowed)
            low = line['confidence'] is not None and line['confidence'] < threshold
            for col in range(3):
                item = self.table.item(i, col)
                if item: item.setBackground(QColor('#fff0ce' if low else '#ffffff'))
        self.line_loading = False
        if select_first and eligible:
            index = self.current_line if self.current_line in allowed else eligible[0]
            self.table.setCurrentCell(index, 2)
            self.scroll_review_row(index)
            self.line_selected(index)
        else:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.current_line = -1
            self.crop_source = QPixmap()
            self.preview.highlight(-1, center=False)
            self.crop.setText('本页没有符合当前分数设置的行' if lines and not eligible else '点击右侧任意一行，查看原文细节')
            if lines and not eligible:
                self.line_note.setText('本页没有待校对的低分行。可调整阈值、关闭筛选，或点「下一行」继续。')
            elif not lines:
                self.line_note.setText('本页尚无可校对文字，请先识别或切换到其他页。')
            self.schedule_crop_alignment()
    def pick_line(self, index):
        if 0 <= index < self.table.rowCount():
            if self.table.isRowHidden(index):
                self.status.setText('该行不在当前低分筛选范围；关闭「只校对低分行」可查看全部行。')
                return
            self.tabs.setCurrentIndex(0)
            self.table.setCurrentCell(index, 2)
            self.scroll_review_row(index)
            self.line_selected(index)
            self.table.setFocus(Qt.FocusReason.ShortcutFocusReason)
    def move_line(self, delta):
        row = self.files.currentRow()
        if row < 0: return
        indices = self.review_indices(self.entries[row])
        candidates = [i for i in indices if i > self.current_line] if delta > 0 else [i for i in indices if i < self.current_line]
        if candidates:
            self.pick_line(candidates[0] if delta > 0 else candidates[-1])
            return
        if delta < 0: return
        for next_row in range(row+1, len(self.entries)):
            entry = self.entries[next_row]
            pending = entry['state'] == '待识别' or entry['state'].startswith('失败')
            next_indices = self.review_indices(entry)
            if not pending and not next_indices: continue
            self.files.setCurrentRow(next_row)
            self.mark_dirty()
            if pending:
                if not self.worker.isRunning(): self.start(True)
                else:
                    self.pending_navigation = next_row
                    self.status.setText('已进入下一页，当前任务结束后会自动识别此页。')
            return
        self.status.setText('已到最后一页，当前设置下没有后续待校对行。')
    def simplify_current(self):
        row = self.files.currentRow()
        if row < 0 or self.worker.isRunning(): return
        entry = self.entries[row]
        if not entry.get('lines'):
            self.status.setText('当前页没有可转换的文字，请先识别。')
            return
        try:
            converted = [to_simplified(line['text']) for line in entry['lines']]
            for line, text in zip(entry['lines'], converted): line['text'] = text
            entry['text'] = '\n'.join(converted)
            self.loading = True
            self.editor.setPlainText(entry['text'])
            self.loading = False
            self.refresh_lines()
            self.mark_dirty()
            self.status.setText('当前页已转换为简体，原始识别和文字坐标保留。')
        except Exception as exc:
            QMessageBox.warning(self, '繁转简失败', str(exc))
    def edit_selected(self):
        item = self.table.item(self.current_line, 2)
        if item is not None and not self.worker.isRunning() and self.table.state() != QAbstractItemView.State.EditingState:
            self.table.setCurrentCell(self.current_line, 2)
            self.table.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.table.editItem(item)
    def finish_line_edit(self, accepted):
        def resume():
            if self.table.isVisible() and self.tabs.currentIndex() == 0:
                self.table.setFocus(Qt.FocusReason.ShortcutFocusReason)
                self.status.setText('修改已确认 · ↑ / ↓ 切换行，Enter 继续修改。' if accepted else '已取消本次修改 · ↑ / ↓ 继续校对。')
                self.schedule_crop_alignment()
        QTimer.singleShot(0, resume)
    def line_selected(self, index):
        if self.line_loading: return
        if index >= 0 and self.table.isRowHidden(index): return
        row = self.files.currentRow()
        if row < 0: return
        lines = self.entries[row].get('lines', [])
        if not 0 <= index < len(lines): return
        self.current_line = index
        line = lines[index]
        self.preview.highlight(index)
        if line['box'] is not None and not self.source_pix.isNull():
            xs, ys = [p[0] for p in line['box']], [p[1] for p in line['box']]
            x, y = max(0, int(min(xs))-10), max(0, int(min(ys))-8)
            right, bottom = min(self.source_pix.width(), int(max(xs))+10), min(self.source_pix.height(), int(max(ys))+8)
            self.crop_source = self.source_pix.copy(x, y, right-x, bottom-y)
            self.align_crop()
            status = '已修改' if line['text'] != line['original'] else '未修改'
            self.line_note.setText(f'第 {index+1} 行 · {status}\n原始识别：{line["original"]}\n置信度反映初始识别，修改后不重新计算。')
        else:
            self.crop_source = QPixmap()
            self.crop.setText('手动新增或重新分段的文字，没有对应的原图位置')
            self.line_note.setText(f'第 {index+1} 行 · 手动文字，无原图定位')
            self.align_crop()
    def line_edited(self, item):
        if self.line_loading or item.column() != 2: return
        row = self.files.currentRow()
        if row < 0: return
        entry = self.entries[row]
        entry['lines'][item.row()]['text'] = item.text()
        self.line_loading = True
        item.setForeground(QColor('#327249') if item.text() != entry['lines'][item.row()]['original'] else QColor('#25382c'))
        self.line_loading = False
        entry['text'] = '\n'.join(line['text'] for line in entry['lines'])
        self.loading = True
        self.editor.setPlainText(entry['text'])
        self.loading = False
        self.line_selected(item.row())
        self.mark_dirty()
    def start(self, only_current=False):
        if self.worker.isRunning(): return
        if not self.entries:
            self.status.setText('请先导入 PDF 或图片。')
            return
        jobs = [(i, source_ref(e)) for i, e in enumerate(self.entries)
                if (not only_current or i == self.files.currentRow())
                and (e['state'] == '待识别' or e['state'].startswith('失败'))]
        if not jobs:
            self.status.setText('所选页面已识别，可直接校对。已完成页面不会重复识别或覆盖修改。')
            return
        self.worker.jobs = jobs
        for btn in (self.add_btn, self.paste_btn, self.current_btn, self.run_btn, self.clear_btn, self.open_project_btn): btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.simplify_check.setEnabled(False)
        self.simplify_btn.setEnabled(False)
        self.editor.setReadOnly(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bar.setRange(0, len(jobs))
        self.bar.setValue(0)
        self.bar.show()
        self.status.setText('正在本机识别… 首次加载模型可能需要几秒。')
        self.worker.start()
    def on_result(self, index, result):
        entry = self.entries[index]
        # Convert before committing so a conversion failure cannot leave a
        # half-converted page marked as completed.
        try:
            lines = [{'box': box, 'original': text,
                      'text': to_simplified(text) if self.simplify_check.isChecked() else text,
                      'confidence': confidence} for box, text, confidence in result['boxes']]
        except Exception as exc:
            self.on_error(index, '繁转简失败：'+str(exc))
            return
        entry.update(result)
        entry['lines'] = lines
        entry['text'] = '\n'.join(line['text'] for line in lines)
        n = len(entry['boxes'])
        entry['state'] = f'已完成 · {n} 行 · {result["seconds"]} 秒' if n else '已完成 · 未检测到文字'
        self.files.item(index).setText(entry_label(entry) + '\n' + entry['state'])
        if self.files.currentRow() == index: self.select(index)
        self.mark_dirty()
        self.status.setText(f'正在处理 · {entry_label(entry)} 已完成')
    def on_error(self, index, error):
        entry = self.entries[index]
        entry['state'] = '失败：' + error
        self.files.item(index).setText(entry_label(entry) + '\n识别失败（可重试）')
        if self.files.currentRow() == index: self.update_preview()
        self.mark_dirty()
    def done(self):
        for btn in (self.add_btn, self.paste_btn, self.current_btn, self.run_btn, self.clear_btn, self.open_project_btn): btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.simplify_check.setEnabled(True)
        self.simplify_btn.setEnabled(True)
        self.editor.setReadOnly(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        errors = sum(e['state'].startswith('失败') for e in self.entries)
        pending = sum(e['state'] == '待识别' for e in self.entries)
        self.status.setText(f'本批次结束 · 待识别 {pending} 页 · 失败 {errors} 页 · 可校对或继续识别')
        self.bar.hide()
        if self.project_file and self.dirty: self.save_project(automatic=True)
        pending_navigation = self.pending_navigation
        self.pending_navigation = None
        if pending_navigation == self.files.currentRow() and pending_navigation is not None:
            if self.entries[pending_navigation]['state'] == '待识别':
                QTimer.singleShot(0, lambda: self.start(True))
    def stop(self):
        self.pending_navigation = None
        self.worker.requestInterruption()
        self.stop_btn.setEnabled(False)
        self.status.setText('将在当前页完成后停止；已完成页面和纠错内容会保留。')
    def move_page(self, delta):
        row = self.files.currentRow()+delta
        if 0 <= row < len(self.entries): self.files.setCurrentRow(row)
    def update_page_count(self):
        self.count_label.setText(f'页面队列 / {len(self.entries)}')
        self.page_spin.setRange(1, len(self.entries)) if self.entries else self.page_spin.setRange(0, 0)
    def clear(self):
        if self.worker.isRunning(): return
        if not self.confirm_saved(): return
        self.autosave.stop()
        self.project_file = None
        self.dirty = False
        self.entries.clear()
        self.files.clear()
        self.update_page_count()
        self.update_project_label()
        self.select(-1)
        self.status.setText('已清空，准备就绪。')
    def copy_text(self):
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.status.setText('当前文字已复制。')
    def save_text(self, text, default):
        if not text.strip():
            self.status.setText('没有可导出的文字。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出文字', default, '文本文件 (*.txt)')
        if path:
            try:
                Path(path).write_text(text, encoding='utf-8-sig')
                self.status.setText('已保存：' + path)
            except OSError as exc:
                QMessageBox.warning(self, '保存失败', str(exc))
    def export_current(self):
        row = self.files.currentRow()
        name = Path(self.entries[row]['path']).stem if row >= 0 else '识别结果'
        if row >= 0 and self.entries[row].get('page') is not None: name += f'_第{self.entries[row]["page"]+1}页'
        self.save_text(self.editor.toPlainText(), name + '.txt')
    def export_all(self):
        text = '\n\n'.join(f'===== {entry_label(e)} =====\n{e["text"]}' for e in self.entries if e['text'].strip())
        self.save_text(text, '墨识_全部结果.txt')
    def mark_dirty(self, checked=None):
        if self.saving: return
        self.dirty = True
        self.update_project_label()
        if self.project_file and not self.autosave.isActive(): self.autosave.start()
    def update_project_label(self):
        name = Path(self.project_file).name if self.project_file else '尚未保存进度'
        self.project_label.setText(name + (' · 有未保存修改' if self.dirty else ' · 已保存') if self.project_file else name + ' · 首次保存后自动更新')
    def default_project_name(self):
        row = self.files.currentRow()
        current = self.entries[row] if 0 <= row < len(self.entries) else None
        pdf = current if current and Path(current['path']).suffix.lower() == '.pdf' else next(
            (entry for entry in self.entries if Path(entry['path']).suffix.lower() == '.pdf'), None)
        source = pdf or current or (self.entries[0] if self.entries else None)
        return Path(source['path']).stem+'.inkocr' if source else '电子书校对.inkocr'
    def save_project(self, checked=False, automatic=False):
        if not self.entries: return False
        self.autosave.stop()
        path = self.project_file
        if not path:
            if automatic: return False
            path, _ = QFileDialog.getSaveFileName(self, '保存校对进度', self.default_project_name(), '墨识校对进度 (*.inkocr)')
            if not path: return False
            if Path(path).suffix.lower() != '.inkocr': path += '.inkocr'
        try:
            records = []
            for entry in self.entries:
                record = dict(entry)
                if Path(self.temp.name) in Path(entry['path']).parents:
                    record['embedded_image'] = base64.b64encode(Path(entry['path']).read_bytes()).decode('ascii')
                records.append(record)
            payload = {'format':'inkocr', 'version':3, 'entries':records, 'selected_page':self.files.currentRow(),
                       'settings': {'simplify_after_ocr': self.simplify_check.isChecked(),
                                    'score_threshold': self.score_threshold.value(),
                                    'low_only': self.low_only.isChecked(),
                                    'comparison_mode': 'vertical' if self.comparison_mode.currentIndex() == 1 else 'horizontal'}}
            # Replace atomically: interrupted writes never overwrite the last good save.
            target = Path(path)
            fd, temporary = tempfile.mkstemp(prefix=target.name+'.', suffix='.tmp', dir=target.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            self.project_file = str(target.resolve())
            self.dirty = False
            self.update_project_label()
            return True
        except Exception as exc:
            self.project_label.setText('保存失败：' + str(exc))
            if not automatic: QMessageBox.warning(self, '保存进度失败', str(exc))
            return False
    def confirm_saved(self):
        if not self.dirty: return True
        if self.project_file and self.save_project(automatic=True): return True
        answer = QMessageBox.question(self, '保存校对进度', '当前有未保存内容，是否保存校对进度？',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel: return False
        return self.save_project() if answer == QMessageBox.StandardButton.Save else True
    def open_project(self):
        if self.worker.isRunning(): return
        path, _ = QFileDialog.getOpenFileName(self, '打开校对进度', '', '墨识校对进度 (*.inkocr)')
        if path: self.load_project(path)
    def load_project(self, path):
        if self.worker.isRunning(): return False
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            if data.get('format') != 'inkocr' or data.get('version') != 3 or not isinstance(data.get('entries'), list):
                raise ValueError('不是支持的墨识校对进度文件。')
            records = data['entries']
            if not records: raise ValueError('进度文件没有页面。')
            checked = {}
            for i, record in enumerate(records):
                if not isinstance(record, dict) or not isinstance(record.get('text'), str): raise ValueError('页面数据不完整。')
                if record.get('embedded_image'):
                    local = Path(self.temp.name) / f'恢复图片_{time.time_ns()}_{i}.png'
                    local.write_bytes(base64.b64decode(record.pop('embedded_image'), validate=True))
                    record['path'] = str(local)
                    stat = local.stat()
                    record.update(source_size=stat.st_size, source_mtime=stat.st_mtime_ns)
                source = str(Path(record['path']).resolve())
                record['path'] = source
                if source not in checked:
                    stat = Path(source).stat()
                    if stat.st_size != record['source_size'] or stat.st_mtime_ns != record['source_mtime']:
                        raise ValueError(f'原文件已变化，请重新导入，避免校对位置错位：{source}')
                    count = None
                    if Path(source).suffix.lower() == '.pdf':
                        import pypdfium2 as pdfium
                        with PDF_LOCK, pdfium.PdfDocument(source) as doc: count = len(doc)
                    checked[source] = count
                page = record.get('page')
                if page is not None and (type(page) is not int or checked[source] is None or not 0 <= page < checked[source]):
                    raise ValueError('PDF 页码超出原文件范围。')
                if not isinstance(record.get('state'), str): raise ValueError('缺少页面识别状态。')
                for line in record.get('lines', []):
                    if not isinstance(line.get('text'), str): raise ValueError('校对行数据无效。')
                    box = line.get('box')
                    if box is not None and (len(box) != 4 or not np.isfinite(np.asarray(box, dtype=float)).all() or np.asarray(box).shape != (4, 2)):
                        raise ValueError('文字坐标无效。')
            if not self.confirm_saved(): return False
            self.autosave.stop()
            self.saving = True
            self.simplify_check.setChecked(bool(data.get('settings', {}).get('simplify_after_ocr', True)))
            self.score_threshold.blockSignals(True)
            self.low_only.blockSignals(True)
            self.score_threshold.setValue(float(data.get('settings', {}).get('score_threshold', 90.0)))
            self.low_only.setChecked(bool(data.get('settings', {}).get('low_only', False)))
            self.score_threshold.blockSignals(False)
            self.low_only.blockSignals(False)
            self.comparison_mode.blockSignals(True)
            self.comparison_mode.setCurrentIndex(1 if data.get('settings', {}).get('comparison_mode') == 'vertical' else 0)
            self.comparison_mode.blockSignals(False)
            self.change_comparison_layout(persist=False)
            self.files.blockSignals(True)
            self.files.clear()
            self.entries = records
            for entry in records: self.files.addItem(entry_label(entry)+'\n'+entry['state'])
            self.files.blockSignals(False)
            self.project_file = str(Path(path).resolve())
            self.dirty = False
            self.preview_path = None
            self.update_page_count()
            self.files.setCurrentRow(max(0, min(int(data.get('selected_page', 0)), len(records)-1)))
            self.select(self.files.currentRow())
            self.update_project_label()
            self.status.setText('校对进度已恢复，未识别页面可继续处理。')
            return True
        except Exception as exc:
            QMessageBox.warning(self, '打开进度失败', f'{exc}\n请保留原 PDF / 图片及其所在位置。')
            return False
        finally: self.saving = False
    def closeEvent(self, event):
        if self.worker.isRunning():
            self.stop()
            self.status.setText('正在完成当前页并停止，请稍后再次关闭。')
            event.ignore()
            return
        if not self.confirm_saved():
            event.ignore()
            return
        self.temp.cleanup()
        event.accept()

def main():
    if '--self-test' in sys.argv:
        # No socket connections are allowed during this offline validation.
        import socket
        def blocked(*args, **kwargs): raise RuntimeError('Network disabled by offline test')
        socket.socket.connect = blocked
        socket.create_connection = blocked
        pos = sys.argv.index('--self-test')
        result = recognize(make_engine(), sys.argv[pos+1])
        result['simplified_text'] = to_simplified(result['text'])
        Path(sys.argv[pos+2]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return
    app = QApplication(sys.argv)
    configure_fonts(app)
    app.setApplicationName('Ink OCR')
    window = Window()
    window.show()
    if '--smoke-test' in sys.argv:
        pos = sys.argv.index('--smoke-test')
        window.add_files([sys.argv[pos+1]])
        window.start()
        def capture():
            if window.worker.isRunning(): QTimer.singleShot(500, capture)
            else:
                window.done()
                if window.table.rowCount(): window.pick_line(min(4, window.table.rowCount()-1))
                app.processEvents()
                window.grab().save(sys.argv[pos+2])
                window.dirty = False
                window.close()
        QTimer.singleShot(1000, capture)
    else:
        paths = [p for p in sys.argv[1:] if Path(p).suffix.lower() in EXTENSIONS | {'.pdf', '.inkocr'}]
        if len(paths) == 1 and Path(paths[0]).suffix.lower() == '.inkocr': window.load_project(paths[0])
        else: window.add_files(paths)
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
