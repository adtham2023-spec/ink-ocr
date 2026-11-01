from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

pages = []
font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 42)
for number in range(1, 4):
    im = Image.open('outputs/中英文测试图片.png').convert('RGB')
    d = ImageDraw.Draw(im)
    d.rectangle((50, 890, 1450, 990), fill='white')
    d.text((90, 910), f'电子书扫描测试  Page {number} / 3', font=font, fill='#26362c')
    pages.append(im)
Path('work/pdf-test').mkdir(exist_ok=True)
pages[0].save('work/pdf-test/扫描书样本.pdf', save_all=True, append_images=pages[1:], resolution=150)
print('Created three-page image-only scanned PDF fixture')
