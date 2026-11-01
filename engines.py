"""Local OCR adapters. No downloads or network calls at recognition time."""
import sys
from pathlib import Path
from PIL import Image

def tessdata_path():
    return (Path(sys._MEIPASS)/'tessdata' if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parent/'assets/tessdata')

class TesseractEngine:
    def __init__(self, language='chi_sim+eng'):
        import tesserocr
        self.language = language
        for name in language.split('+'):
            if not (tessdata_path()/(name+'.traineddata')).exists():
                raise RuntimeError('缺少本地语言模型，请运行 python scripts/fetch_tessdata.py')

    def __call__(self, bgr):
        import tesserocr as tess
        rows = []
        # Each call owns its native instance, including when workers restart.
        with tess.PyTessBaseAPI(path=str(tessdata_path()), lang=self.language,
                               psm=tess.PSM.AUTO, oem=tess.OEM.LSTM_ONLY) as api:
            api.SetImage(Image.fromarray(bgr[:, :, ::-1].copy()))
            api.Recognize()
            iterator = api.GetIterator()
            if iterator:
                level = tess.RIL.TEXTLINE
                while True:
                    text = (iterator.GetUTF8Text(level) or '').strip()
                    box = iterator.BoundingBox(level)
                    if text and box:
                        x, y, right, bottom = box
                        rows.append([[[x,y],[right,y],[right,bottom],[x,bottom]], text,
                                     max(0., min(1., iterator.Confidence(level)/100))])
                    if not iterator.Next(level): break
        return rows, None
