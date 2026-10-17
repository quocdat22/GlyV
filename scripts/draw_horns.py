"""Render review-only horns and D strokes; never write a font file."""
from io import BytesIO
from pathlib import Path
import hashlib
import json

from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from draw_marks import ROOT, SOURCE, outline, bounds, transformed


OUT = ROOT / 'sheets/horns-strokes-v1'


def main(root=ROOT, source=SOURCE, out=OUT, calibration=None):
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    font = TTFont(source)
    gs = font.getGlyphSet()
    from calibration import calibrate
    calibration = calibration or calibrate(source)
    cmap = font.getBestCmap()
    additions = {name: outline(data['commands']) for name, data in calibration['glyphs'].items()}
    drawings = {}
    for base, addition in additions.items():
        drawing = RecordingPen()
        gs[cmap[ord(base)]].draw(drawing)
        drawings[cmap[ord(base)]] = drawing
        b, a = bounds(drawing), bounds(addition)
        assert max(b[0], a[0]) < min(b[2], a[2])
        assert max(b[1], a[1]) < min(b[3], a[3])
        assert addition.value[-1][0] == 'closePath'

    top = font['CFF '].cff.topDictIndex[0]
    cs = top.CharStrings
    order = font.getGlyphOrder()
    previews = {}
    for i, (base, addition) in enumerate(additions.items()):
        name = f'review_horn_stroke_{base}'
        pen = T2CharStringPen(gs[cmap[ord(base)]].width, None)
        drawings[cmap[ord(base)]].replay(pen)
        addition.replay(pen)
        cs.charStrings[name] = len(cs.charStringsIndex)
        cs.charStringsIndex.append(pen.getCharString(private=top.Private, globalSubrs=cs.globalSubrs))
        order.append(name)
        font['hmtx'].metrics[name] = (gs[cmap[ord(base)]].width, 0)
        for table in font['cmap'].tables:
            if table.isUnicode():
                table.cmap[0xE000+i] = name
        previews[base] = chr(0xE000+i)
    font.setGlyphOrder(order)
    font['maxp'].numGlyphs = len(order)
    data = BytesIO()
    font.save(data)
    data.seek(0)
    large = ImageFont.truetype(data, 170)
    data.seek(0)
    text_size = ImageFont.truetype(data, 34)
    labels_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    title = ImageFont.truetype(labels_path, 30)
    label = ImageFont.truetype(labels_path, 20)
    small = ImageFont.truetype(labels_path, 17)
    image = Image.new('RGB', (1480, 200+len(additions)*218), '#f4f6f8')
    d = ImageDraw.Draw(image)
    d.text((30, 22), f'{source.stem} | rau & gach v1 | review only', font=title, fill='#172334')
    d.text((30, 73), 'Original outlines retained. Horns and crossbars are draft additions; no output font saved.', font=small, fill='#526174')
    for x, text in [(260, 'Original'), (620, 'Proposed'), (1100, 'Outline detail: new part in blue')]:
        d.text((x, 120), text, font=label, anchor='mt', fill='#526174')
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1200">', '<rect width="2400" height="1200" fill="white"/>']
    report = {'source': str(source), 'status': 'review-only; no output font', 'units_per_em': calibration['units_per_em'], 'glyphs': {}}
    for row, (base, addition) in enumerate(additions.items()):
        y = 165+row*218
        for x, width in [(90, 330), (450, 330), (810, 630)]:
            d.rounded_rectangle((x, y, x+width, y+204), 8, fill='white', outline='#d9dfe6')
        d.text((25, y+80), base, font=label, fill='#526174')
        for x, char in [(255, base), (615, previews[base])]:
            d.line((x-140, y+157, x+140, y+157), fill='#e5eaf0')
            d.text((x, y+157), char, font=large, anchor='ms', fill='#172334')
        baseline = y+157
        left = 1010
        # Pillow handles the typeface; SVG retains exact vectors for color inspection.
        d.text((left, baseline), previews[base], font=large, anchor='ls', fill='#172334')
        shape = transformed(addition, (170/calibration['units_per_em'], 0, 0, -170/calibration['units_per_em'], left, baseline))
        # Sample the cubic paths for the colored PNG overlay only; SVG remains cubic.
        from fontTools.pens.basePen import BasePen

        class OverlayPen(BasePen):
            def _moveTo(self, p):
                self.points = [p]

            def _lineTo(self, p):
                self.points.append(p)

            def _curveToOne(self, p1, p2, p3):
                p0 = self._getCurrentPoint()
                for step in range(1, 33):
                    t = step/32
                    self.points.append(tuple((1-t)**3*p0[k]+3*(1-t)**2*t*p1[k]+3*(1-t)*t*t*p2[k]+t**3*p3[k] for k in (0, 1)))

            def _closePath(self):
                d.polygon(self.points, fill='#2376b9')

        shape.replay(OverlayPen(None))
        for pen, color in [(drawings[cmap[ord(base)]], '#172334'), (addition, '#2376b9')]:
            p = SVGPathPen(None)
            pen.replay(p)
            scale = 620/calibration['units_per_em']
            svg.append(f'<path transform="translate({160+(row%3)*800} {510+(row//3)*580}) scale({scale} {-scale})" fill="{color}" d="{p.getCommands()}"/>')
        svg.append(f'<text x="{200+(row%3)*800}" y="{550+(row//3)*580}" font-size="30">{base} + addition</text>')
        d.text((900, y+178), f'{base}  /  ', font=small, fill='#526174')
        d.text((976, y+171), (base+' '+previews[base]+' ')*4, font=text_size, fill='#172334')
        report['glyphs'][base] = {'original_advance': gs[cmap[ord(base)]].width, 'addition_bounds': bounds(addition), 'commands': addition.value}
    svg.append('</svg>')
    out.mkdir(parents=True, exist_ok=True)
    image.save(out / 'horns-strokes.png')
    (out / 'horns-strokes.svg').write_text('\n'.join(svg))
    (out / 'outlines.json').write_text(json.dumps(report, indent=2)+'\n')
    with Image.open(out / 'horns-strokes.png') as check:
        check.verify()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    path = root / 'manifest.json'
    manifest = json.loads(path.read_text())
    for item in out.iterdir():
        manifest['sha256'][str(item.relative_to(root))] = hashlib.sha256(item.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'{out}: {len(additions)} drafts rendered; source font unchanged.')


if __name__ == '__main__':
    main()
