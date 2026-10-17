"""Draw review-only Vietnamese marks; save SVG outlines and PNG specimens, no OTF.

Run from the project root: .venv/bin/python scripts/draw_marks.py
"""
from io import BytesIO
from pathlib import Path
import hashlib
import json

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont


ROOT = Path('artifacts/sample')
SOURCE = ROOT / 'otf/source.otf'
OUT = ROOT / 'sheets/marks-v1'


def outline(commands):
    pen = RecordingPen()
    for operation, points in commands:
        getattr(pen, operation)(*points)
    return pen


def bounds(pen):
    result = BoundsPen(None)
    pen.replay(result)
    return result.bounds


def transformed(pen, matrix):
    result = RecordingPen()
    pen.replay(TransformPen(result, matrix))
    return result


def centered(pen):
    x0, y0, x1, _ = bounds(pen)
    return transformed(pen, (1, 0, 0, 1, -(x0+x1)/2, -y0))


def main(root=ROOT, source=SOURCE, out=OUT, calibration=None):
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    font = TTFont(source)
    gs = font.getGlyphSet()
    from calibration import calibrate, compose
    calibration = calibration or calibrate(source)
    cmap = font.getBestCmap()
    upm = calibration['units_per_em']
    marks = {name: outline(data['commands']) for name, data in calibration['marks'].items()}
    additions = {name: outline(data['commands']) for name, data in calibration['glyphs'].items()}
    top_dict = font['CFF '].cff.topDictIndex[0]
    charstrings = top_dict.CharStrings
    glyph_order = font.getGlyphOrder()
    preview_count = 0

    def preview(parts, width):
        nonlocal preview_count
        width = round(width)
        name = f'review{preview_count}'
        code = 0xE000 + preview_count
        preview_count += 1
        pen = T2CharStringPen(width, None)
        for drawing, matrix in parts:
            drawing.replay(TransformPen(pen, matrix))
        charstrings.charStrings[name] = len(charstrings.charStringsIndex)
        charstrings.charStringsIndex.append(pen.getCharString(private=top_dict.Private, globalSubrs=charstrings.globalSubrs))
        glyph_order.append(name)
        font['hmtx'].metrics[name] = (width, 0)
        for table in font['cmap'].tables:
            if table.isUnicode():
                table.cmap[code] = name
        return chr(code)

    def specimen(base, shape=None, tone=None):
        drawing, _, _, width = compose(font, base, shape, tone, marks, additions, calibration)
        return preview([(drawing, (1, 0, 0, 1, 0, 0))], width)

    isolated = {name: preview([(pen, (1, 0, 0, 1, upm*.35, upm*.12))], upm*.7) for name, pen in marks.items()}
    tones = [None, 'grave', 'acute', 'hookabove', 'tilde', 'dotbelow']
    rows = [('a', None), ('e', None), ('o', None), ('u', None),
            ('A', None), ('E', None), ('O', None), ('U', None),
            ('a', 'circumflex'), ('a', 'breve'), ('e', 'circumflex'), ('o', 'circumflex'),
            ('A', 'circumflex'), ('A', 'breve'), ('E', 'circumflex'), ('O', 'circumflex')]
    rows = [(base, shape) for base, shape in rows if ord(base) in cmap]
    samples = [[specimen(base, shape, tone) for tone in tones] for base, shape in rows]
    font.setGlyphOrder(glyph_order)
    font['maxp'].numGlyphs = len(glyph_order)
    data = BytesIO()
    font.save(data)
    data.seek(0)
    render = ImageFont.truetype(data, 92)
    data.seek(0)
    large = ImageFont.truetype(data, 160)
    labels_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    label = ImageFont.truetype(labels_path, 17)
    small = ImageFont.truetype(labels_path, 14)
    title = ImageFont.truetype(labels_path, 30)
    out.mkdir(parents=True, exist_ok=True)

    image = Image.new('RGB', (1500, 620), '#f4f6f8')
    d = ImageDraw.Draw(image)
    d.text((30, 22), f'{source.stem} | bo dau v1 | review only', font=title, fill='#172334')
    d.text((30, 72), f'Acute: {calibration["acute_source"]}. Stem: {calibration["stem"]:.1f} units. Slant: {calibration["italic_angle"]:.1f} degrees.', font=label, fill='#526174')
    for i, (name, char) in enumerate(isolated.items()):
        x = 30 + i*207
        d.rounded_rectangle((x, 126, x+195, 390), 8, fill='white', outline='#d9dfe6')
        d.text((x+97, 300), char, font=large, anchor='ms', fill='#172334')
        d.text((x+97, 330), name, font=label, anchor='mt', fill='#172334')
        box = bounds(marks[name])
        d.text((x+97, 360), f'{box[2]-box[0]:.0f} x {box[3]-box[1]:.0f} units', font=small, anchor='mt', fill='#526174')
    d.text((30, 432), 'Original eacute', font=label, fill='#526174')
    d.text((310, 432), 'Proposed e + acute', font=label, fill='#526174')
    if ord('é') in cmap and ord('e') in cmap:
        d.text((120, 570), 'é', font=render, anchor='ms', fill='#172334')
        row = next(i for i, (base, shape) in enumerate(rows) if base == 'e' and shape is None)
        d.text((420, 570), samples[row][2], font=render, anchor='ms', fill='#172334')
    else:
        d.text((40, 510), 'No native eacute in this subset; measured template used if needed.', font=label, fill='#526174')
    d.text((630, 475), 'No final glyphs or output font have been saved.', font=label, fill='#526174')
    image.save(out / 'marks.png')

    image = Image.new('RGB', (1500, 160+len(rows)*158), '#f4f6f8')
    d = ImageDraw.Draw(image)
    d.text((30, 22), f'{source.stem} | placement study v1', font=title, fill='#172334')
    d.text((30, 68), 'Preview compositions only. Uppercase marks use 85% scale; stacked tones use 80%.', font=label, fill='#526174')
    for col, text in enumerate(['base', 'grave', 'acute', 'hook above', 'tilde', 'dot below']):
        d.text((280+col*215, 113), text, font=label, anchor='mt', fill='#526174')
    for row, ((base, shape), chars) in enumerate(zip(rows, samples)):
        y = 150+row*158
        d.text((24, y+60), base + (' + '+shape if shape else ''), font=label, fill='#526174')
        for col, char in enumerate(chars):
            x = 190+col*215
            d.rounded_rectangle((x, y, x+190, y+148), 8, fill='white', outline='#d9dfe6')
            d.line((x+12, y+116, x+178, y+116), fill='#e5eaf0')
            d.text((x+95, y+116), char, font=render, anchor='ms', fill='#172334')
    image.save(out / 'placements.png')

    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2100 380">',
           '<rect width="2100" height="380" fill="white"/>']
    report = {'source': str(source), 'units_per_em': font['head'].unitsPerEm,
              'status': 'review-only; no output font', 'marks': {}, 'calibration': {k: v for k, v in calibration.items() if k not in ('marks', 'glyphs')}}
    for i, (name, pen) in enumerate(marks.items()):
        svg_pen = SVGPathPen(None)
        pen.replay(svg_pen)
        svg.append(f'<path transform="translate({150+i*300} 240) scale({1000/upm} {-1000/upm})" d="{svg_pen.getCommands()}"/>')
        svg.append(f'<text x="{150+i*300}" y="300" text-anchor="middle" font-size="22">{name}</text>')
        report['marks'][name] = {'bounds': bounds(pen), 'commands': pen.value}
    svg.append('</svg>')
    (out / 'marks.svg').write_text('\n'.join(svg))
    (out / 'outlines.json').write_text(json.dumps(report, indent=2) + '\n')
    for name in ('marks.png', 'placements.png'):
        with Image.open(out / name) as check:
            check.verify()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for path in sorted(out.iterdir()):
        manifest['sha256'][str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{out}: 7 marks, {len(rows)*6} placement previews; source font unchanged.')


if __name__ == '__main__':
    main()
