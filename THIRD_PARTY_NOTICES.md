# Third-party components

The MIT license in this repository covers the original Ink OCR application code. Third-party libraries, OCR models and conversion dictionaries keep their upstream licenses and notices.

| Component | Role | Upstream |
| --- | --- | --- |
| RapidOCR / rapidocr-onnxruntime | OCR pipeline and bundled model resources | https://github.com/RapidAI/RapidOCR |
| PaddleOCR | Underlying PP-OCR model family used by RapidOCR resources | https://github.com/PaddlePaddle/PaddleOCR |
| ONNX Runtime | Local model inference | https://github.com/microsoft/onnxruntime |
| PySide6 / Qt | Desktop UI and dynamic Qt libraries | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| pypdfium2 / PDFium | PDF rendering | https://github.com/pypdfium2-team/pypdfium2 |
| OpenCC Python / OpenCC dictionaries | Traditional-to-Simplified conversion | https://github.com/yichen0831/opencc-python |
| NumPy, Pillow, OpenCV, Shapely, pyclipper and other runtime dependencies | Image and geometry processing | See installed package metadata and included notices |
| PyInstaller | Windows packaging | https://github.com/pyinstaller/pyinstaller |

Windows distributions retain their dynamic library directory and include `third-party-licenses/`, collected from installed package distributions. Source code and build instructions are included with the published distribution. The application does not relicense its dependencies or models as MIT.

The examples, icon and screenshots were created for this project. No proprietary ebook pages or personal proofreading projects are included in this repository.
