import os
try:
    from PIL import Image, ImageDraw
except ImportError:
    print("请先在终端运行: pip install Pillow")
    exit()

# 严格按照目录结构创建文件夹
os.makedirs('assets/matrix_pool/y_overlay/logos', exist_ok=True)
os.makedirs('assets/matrix_pool/y_overlay/stickers', exist_ok=True)

print("🏭 正在生成 Y 轴透明测试素材...")

# ==========================================
# 1. 制造 3 款测试 Logo (半透明)
# ==========================================
# 款式 A: 科技蓝 (圆角矩形)
l1 = Image.new('RGBA', (400, 150), (0, 0, 0, 0))
d1 = ImageDraw.Draw(l1)
d1.rounded_rectangle([(10, 10), (390, 140)], radius=20, fill=(0, 102, 204, 200), outline=(255, 255, 255, 255), width=5)
d1.rectangle([(50, 40), (350, 110)], outline=(255, 255, 255, 150), width=2)
l1.save('assets/matrix_pool/y_overlay/logos/logo_1_blue.png')

# 款式 B: 环保绿 (带内圆的扁平风)
l2 = Image.new('RGBA', (400, 150), (0, 0, 0, 0))
d2 = ImageDraw.Draw(l2)
d2.rounded_rectangle([(10, 10), (390, 140)], radius=40, fill=(46, 139, 87, 210), outline=(255, 215, 0, 255), width=5)
d2.ellipse([(50, 30), (140, 120)], fill=(255, 255, 255, 150))
l2.save('assets/matrix_pool/y_overlay/logos/logo_2_green.png')

# 款式 C: 工业黑/深灰 (六边形硬核风)
l3 = Image.new('RGBA', (400, 150), (0, 0, 0, 0))
d3 = ImageDraw.Draw(l3)
d3.polygon([(10, 75), (50, 10), (350, 10), (390, 75), (350, 140), (50, 140)], fill=(50, 50, 50, 220), outline=(192, 192, 192, 255), width=4)
l3.save('assets/matrix_pool/y_overlay/logos/logo_3_dark.png')
print("✅ 生成 3 款 Logo -> assets/matrix_pool/y_overlay/logos/")


# ==========================================
# 2. 制造 3 款转化贴纸 (高亮、不同形状)
# ==========================================
# 款式 A: 爆款红 (经典大圆盘, 类似 50% OFF)
s1 = Image.new('RGBA', (500, 500), (0, 0, 0, 0))
ds1 = ImageDraw.Draw(s1)
ds1.ellipse([(20, 20), (480, 480)], fill=(220, 20, 60, 230), outline=(255, 215, 0, 255), width=15)
ds1.ellipse([(100, 100), (400, 400)], outline=(255, 255, 255, 200), width=5)
s1.save('assets/matrix_pool/y_overlay/stickers/sticker_1_red.png')

# 款式 B: 限时橙 (菱形警示风)
s2 = Image.new('RGBA', (500, 500), (0, 0, 0, 0))
ds2 = ImageDraw.Draw(s2)
ds2.polygon([(250, 10), (490, 250), (250, 490), (10, 250)], fill=(255, 140, 0, 230), outline=(255, 255, 255, 255), width=10)
ds2.rectangle([(150, 150), (350, 350)], outline=(255, 255, 255, 200), width=8)
s2.save('assets/matrix_pool/y_overlay/stickers/sticker_2_orange.png')

# 款式 C: WhatsApp 绿 (长条药丸状, 模拟带有电话号码的横幅)
s3 = Image.new('RGBA', (600, 200), (0, 0, 0, 0)) 
ds3 = ImageDraw.Draw(s3)
ds3.rounded_rectangle([(10, 10), (590, 190)], radius=90, fill=(37, 211, 102, 240), outline=(255, 255, 255, 255), width=8)
ds3.ellipse([(30, 30), (170, 170)], fill=(255, 255, 255, 200)) # 左侧模拟白色的电话Icon底座
s3.save('assets/matrix_pool/y_overlay/stickers/sticker_3_green.png')
print("✅ 生成 3 款 转化贴纸 -> assets/matrix_pool/y_overlay/stickers/")

print("🎉 全部测试素材准备完毕！可以开始调用 FFmpeg 叠加了！")