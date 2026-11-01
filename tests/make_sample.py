from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

out = Path('outputs')
out.mkdir(exist_ok=True)
im = Image.new('RGB', (1500, 1000), '#ffffff')
d = ImageDraw.Draw(im)
title = ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc', 62)
font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 40)
d.rectangle((0, 0, 1500, 14), fill='#326647')
d.text((90, 90), '中英文混排识别测试', font=title, fill='#203b2a')
lines = ['Ink OCR  本地离线文字识别',
         '项目名称：双语资料整理 Bilingual Documents',
         '客户姓名：张先生 / Mr. Zhang',
         '联系电话：012-345 6789',
         '价格 Price: RM 1,280.50',
         '地址 Address: Kuala Lumpur, Malaysia',
         '无需 API，无需上传图片。',
         'English words, 中文文字, numbers 1234567890.']
for i, line in enumerate(lines):
    d.text((90, 225+i*80), line, font=font, fill='#26362c')
im.save(out / '中英文测试图片.png')
icon = Image.new('RGB', (256, 256), '#326647')
di = ImageDraw.Draw(icon)
di.rounded_rectangle((47, 35, 209, 221), radius=18, fill='#f6faf3')
for y, x in [(83, 172), (119, 172), (155, 144)]:
    di.rounded_rectangle((78, y, x, y+12), radius=5, fill='#326647')
icon.save('work/ink.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])
