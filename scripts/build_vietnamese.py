"""Build the Vietnamese outlines into a CFF OpenType font.

Run from the project root: .venv/bin/python scripts/build_vietnamese.py
"""
from io import BytesIO
from pathlib import Path
from math import ceil, floor, radians, tan
import hashlib
import json
import unicodedata as ud

from fontTools.agl import UV2AGL
from fontTools.misc.timeTools import timestampNow
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont
from fontTools.otlLib.builder import buildStatTable
from PIL import Image, ImageDraw, ImageFont
import uharfbuzz as hb

from draw_marks import ROOT, SOURCE, outline, bounds, transformed
from vietnamese_coverage import vietnamese_characters


OUTPUT = Path('build/source-Vietnamese.otf')
REPORTS = ROOT / 'reports'
SHEET = ROOT / 'sheets/source-Vietnamese.png'
SHAPES = {'\u0302': 'circumflex', '\u0306': 'breve', '\u031b': 'horn'}
TONES = {'\u0300': 'grave', '\u0301': 'acute', '\u0309': 'hookabove',
         '\u0303': 'tilde', '\u0323': 'dotbelow'}


def build(source=SOURCE, output=OUTPUT, marks_path=None, horns_path=None, calibration=None):
    from calibration import calibrate, compose
    calibration = calibration or calibrate(source)
    font = TTFont(source)
    source_gs = font.getGlyphSet()
    cmap = font.getBestCmap().copy()
    upm = font['head'].unitsPerEm
    expected_new = []
    native_family = getattr(font['CFF '].cff.topDictIndex[0], 'FamilyName', None)
    source_name = native_family or font['name'].getDebugName(16) or font['name'].getDebugName(1) or source.stem
    if not native_family and '-' in source_name:
        source_name = source_name.rsplit('-', 1)[0]
    source_names = {number: font['name'].getDebugName(number) for number in (0, 7, 8, 9, 10, 11, 12, 13, 14)
                    if font['name'].getDebugName(number)}
    originals = {}
    for name in font.getGlyphOrder():
        pen = RecordingPen()
        source_gs[name].draw(pen)
        originals[name] = pen
    marks_data = json.loads((marks_path or ROOT / 'sheets/marks-v1/outlines.json').read_text())
    horn_data = json.loads((horns_path or ROOT / 'sheets/horns-strokes-v1/outlines.json').read_text())
    marks = {name: outline(data['commands']) for name, data in marks_data['marks'].items()}
    additions = {name: outline(data['commands']) for name, data in horn_data['glyphs'].items()}
    top = font['CFF '].cff.topDictIndex[0]
    original_notice = getattr(top, 'Notice', '') or source_names.get(0, '')
    if original_notice:
        top.Notice = original_notice.replace('\u00a9', '(c)').encode('ascii', 'backslashreplace').decode()
    charstrings = top.CharStrings
    order = font.getGlyphOrder()
    placements = {}
    for char in vietnamese_characters():
        if ord(char) in cmap:
            continue
        decomposition = ud.normalize('NFD', char)
        base = decomposition[0]
        shape = next((SHAPES[c] for c in decomposition[1:] if c in SHAPES), None)
        tone = next((TONES[c] for c in decomposition[1:] if c in TONES), None)
        if char in '\u0110\u0111':
            base = 'D' if char.isupper() else 'd'
        if ord(base) not in cmap:
            continue
        expected_new.append(char)
        base_name = cmap[ord(base)]
        if char in '\u0110\u0111':
            shape = 'stroke'
        combined, parts, detail, width = compose(font, base, shape, tone, marks, additions, calibration)
        combined_bounds = bounds(combined)
        name = UV2AGL.get(ord(char), f'uni{ord(char):04X}')
        assert name not in order
        pen = T2CharStringPen(width, None)
        combined.replay(pen)
        # CFF stores the composed contours directly (TrueType glyf components do not apply).
        cs = pen.getCharString(private=top.Private, globalSubrs=charstrings.globalSubrs)
        charstrings.charStrings[name] = len(charstrings.charStringsIndex)
        charstrings.charStringsIndex.append(cs)
        order.append(name)
        font['hmtx'].metrics[name] = (width, floor(combined_bounds[0]))
        cmap[ord(char)] = name
        placements[char] = {'glyph': name, 'base': base_name, 'components': [n for n, _ in parts],
                            'marks': detail, 'bounds': combined_bounds, 'advance': width}
    for table in font['cmap'].tables:
        if table.isUnicode():
            table.cmap = cmap.copy()
    font.setGlyphOrder(order)
    top.charset = order
    font['maxp'].numGlyphs = len(order)
    font['head'].created = font['head'].modified = timestampNow()
    font['head'].fontRevision = 1.001
    font['head'].flags |= 2
    name = font['name']
    name.names = []
    family, ps = source_name+' Vietnamese', output.stem
    style = calibration['style']
    bold, italic = calibration['weight_class'] >= 700, calibration['italic_angle'] != 0
    legacy_style = 'Bold Italic' if bold and italic else 'Bold' if bold else 'Italic' if italic else 'Regular'
    legacy_family = family if style in ('Regular', 'Bold', 'Italic', 'Bold Italic') else family+' '+style.replace(' Italic', '')
    for number, value in {1: legacy_family, 2: legacy_style, 3: f'1.001;NONE;{ps}',
                          4: family+' '+style, 5: 'Version 1.001', 6: ps,
                          16: family, 17: style}.items():
        name.setName(value, number, 3, 1, 0x409)
    if original_notice:
        name.setName(original_notice, 0, 3, 1, 0x409)
    for number, value in source_names.items():
        name.setName(value, number, 3, 1, 0x409)
    font['CFF '].cff.fontNames = [ps]
    top.FamilyName, top.FullName, top.Weight = family, family+' '+style, calibration['weight_name']
    font['post'].italicAngle = calibration['italic_angle']
    font['head'].macStyle = (1 if bold else 0) | (2 if italic else 0)
    top.version = '1.001'
    top.UnderlinePosition, top.UnderlineThickness = -upm*.1, upm*.05
    font['post'].underlinePosition, font['post'].underlineThickness = round(-upm*.1), round(upm*.05)
    glyph_set = font.getGlyphSet()
    boxes = {}
    for glyph in order:
        pen = RecordingPen()
        glyph_set[glyph].draw(pen)
        box = bounds(pen)
        if box:
            boxes[glyph] = box
        width, _ = font['hmtx'].metrics[glyph]
        font['hmtx'].metrics[glyph] = (width, floor(box[0]) if box else 0)
    bbox = [floor(min(b[0] for b in boxes.values())), floor(min(b[1] for b in boxes.values())),
            ceil(max(b[2] for b in boxes.values())), ceil(max(b[3] for b in boxes.values()))]
    top.FontBBox = bbox
    hhea = font['hhea']
    hhea.caretSlopeRise = upm if italic else 1
    hhea.caretSlopeRun = round(tan(radians(-calibration['italic_angle']))*upm) if italic else 0
    hhea.ascent, hhea.descent, hhea.lineGap = ceil(bbox[3]+upm*.04), floor(min(-upm*.25, bbox[1]-upm*.04)), 0
    hhea.advanceWidthMax = max(w for w, _ in font['hmtx'].metrics.values())
    hhea.minLeftSideBearing = min(lsb for _, lsb in font['hmtx'].metrics.values())
    hhea.minRightSideBearing = min(font['hmtx'].metrics[g][0]-ceil(b[2]) for g, b in boxes.items())
    hhea.xMaxExtent = max(ceil(b[2]) for b in boxes.values())
    os2 = font['OS/2']
    os2.version = max(4, os2.version)
    os2.usDefaultChar = getattr(os2, 'usDefaultChar', 0)
    os2.usBreakChar = 32 if 32 in cmap else 0
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = hhea.ascent, hhea.descent, 0
    os2.usWinAscent, os2.usWinDescent = hhea.ascent, -hhea.descent
    os2.sxHeight, os2.sCapHeight = round(calibration['x_height']), round(calibration['cap_height'])
    os2.usWeightClass = calibration['weight_class']
    os2.usWidthClass = calibration['width_class']
    os2.fsSelection = 0x80 | (0x20 if bold else 0) | (1 if italic else 0) | (0x40 if not bold and not italic else 0)
    os2.usFirstCharIndex, os2.usLastCharIndex = min(cmap), max(cmap)
    os2.usMaxContext = 1
    os2.yStrikeoutSize, os2.yStrikeoutPosition = round(upm*.035), round(calibration['x_height']*.58)
    os2.ySubscriptXSize, os2.ySubscriptYSize, os2.ySubscriptYOffset = round(upm*.65), round(upm*.6), round(upm*.075)
    os2.ySuperscriptXSize, os2.ySuperscriptYSize, os2.ySuperscriptYOffset = round(upm*.65), round(upm*.6), round(upm*.35)
    os2.recalcAvgCharWidth(font)
    os2.recalcUnicodeRanges(font)
    os2.recalcCodePageRanges(font)
    buildStatTable(font, [
        {'tag': 'wght', 'name': 'Weight', 'values': [{'value': os2.usWeightClass,
         'name': calibration['weight_name'], 'flags': 2 if os2.usWeightClass == 400 else 0}]},
        {'tag': 'wdth', 'name': 'Width', 'values': [{'value': 75 if os2.usWidthClass == 3 else 100,
         'name': 'Condensed' if os2.usWidthClass == 3 else 'Normal', 'flags': 0 if os2.usWidthClass == 3 else 2}]},
        {'tag': 'ital', 'name': 'Italic', 'values': [dict(value=1, name='Italic') if italic
         else dict(value=0, name='Roman', flags=2, linkedValue=1)]},
    ], elidedFallbackName='Regular')
    output.parent.mkdir(parents=True, exist_ok=True)
    font.save(output)
    assert len(placements) == len(expected_new)
    return placements, originals


def validate_and_render(placements, originals, source=SOURCE, output=OUTPUT, sheet=SHEET, reports=REPORTS):
    data = output.read_bytes()
    font = TTFont(BytesIO(data), checkChecksums=2)
    cmap, gs = font.getBestCmap(), font.getGlyphSet()
    available = [c for c in vietnamese_characters() if ord(c) in cmap and cmap[ord(c)] != '.notdef']
    missing = [c for c in vietnamese_characters() if c not in available]
    with TTFont(source) as original:
        source_cmap = original.getBestCmap() or {}
    for c in missing:
        base = ('D' if c.isupper() else 'd') if c in '\u0110\u0111' else ud.normalize('NFD', c)[0]
        assert ord(base) not in source_cmap, f'Expected character was not built: {c}'
    for name, original in originals.items():
        pen = RecordingPen()
        gs[name].draw(pen)
        assert pen.value == original.value, name
    for name in font.getGlyphOrder():
        pen = RecordingPen()
        gs[name].draw(pen)
        box = bounds(pen)
        if box:
            assert font['hhea'].ascent >= ceil(box[3])
            assert font['hhea'].descent <= floor(box[1])
            assert font['OS/2'].usWinAscent >= ceil(box[3])
            assert -font['OS/2'].usWinDescent <= floor(box[1])
    hb_font = hb.Font(hb.Face(data))
    upm = font['head'].unitsPerEm
    hb_font.scale = (upm, upm)

    def shape(text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(hb_font, buf)
        assert all(info.codepoint != 0 for info in buf.glyph_infos), text
        return [(i.codepoint, p.x_advance, p.x_offset, p.y_offset)
                for i, p in zip(buf.glyph_infos, buf.glyph_positions)]

    for c in available:
        assert shape(c) == shape(ud.normalize('NFD', c)), c
    sentence = 'Thuận gió hòa, người Việt Nam yêu đất nước.'
    stress = 'Ắ ằ ẳ ẵ ặ Ấ ầ ẩ ẫ ậ Ơ ờ ở ỡ ợ Ư ừ ử ữ ự Đ đ'
    rows = [sentence, sentence.upper(), stress]
    tones = ['', '\u0300', '\u0301', '\u0309', '\u0303', '\u0323']
    for base in 'aăâeêioôơuưy':
        lower = ' '.join(ud.normalize('NFC', base+t) for t in tones)
        rows.append(lower + '     ' + lower.upper())
    skipped_samples = [text for text in rows if any(ord(c) not in cmap for c in text)]
    rows = [text for text in rows if all(ord(c) in cmap for c in text)]
    if not rows:
        rows = [''.join(available)] if available else [chr(c) for c in source_cmap if source_cmap[c] != '.notdef'][:12]
    for text in rows:
        assert shape(text) == shape(ud.normalize('NFD', text))
    # Temporary glyph-ID mapping lets Pillow render HarfBuzz's exact shaped output.
    order = font.getGlyphOrder()
    for table in font['cmap'].tables:
        if table.isUnicode():
            table.cmap.update({0xE000+i: name for i, name in enumerate(order)})
    render_data = BytesIO()
    font.save(render_data)
    render_data.seek(0)
    render_font = ImageFont.truetype(render_data, 50)
    labels_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    label = ImageFont.truetype(labels_path, 19)
    title = ImageFont.truetype(labels_path, 30)
    pixel_scale = 50/upm
    image_width = max(1600, ceil(max((sum(g[1] for g in shape(text)) for text in rows), default=0)*pixel_scale)+100)
    ascent_px = ceil(font['hhea'].ascent*pixel_scale)
    row_height = max(110, ceil((font['hhea'].ascent-font['hhea'].descent)*pixel_scale)+30)
    image = Image.new('RGB', (image_width, 130+len(rows)*row_height), '#f4f6f8')
    draw = ImageDraw.Draw(image)
    draw.text((32, 20), f'{output.stem} | build 1.001', font=title, fill='#172334')
    draw.text((32, 67), f'HarfBuzz rendering | {len(available)}/134 characters | NFC and NFD verified for available characters', font=label, fill='#526174')
    for row, text in enumerate(rows):
        baseline = 120+ascent_px+row*row_height
        draw.rounded_rectangle((22, 110+row*row_height, image_width-22, 110+(row+1)*row_height-10), 8, fill='white', outline='#d9dfe6')
        x = 45
        for gid, advance, dx, dy in shape(text):
            draw.text((x+dx*pixel_scale, baseline-dy*pixel_scale), chr(0xE000+gid), font=render_font,
                      anchor='ls', fill='#172334')
            x += advance*pixel_scale
        assert x < image_width-22, text
    image.save(sheet)
    with Image.open(sheet) as check:
        check.verify()
    report = {'source': str(source), 'output': str(output), 'total_glyphs': len(order),
              'vietnamese_precomposed': len(available), 'missing_characters': missing, 'skipped_samples': skipped_samples, 'new_glyphs': len(placements),
              'original_glyphs_preserved': len(originals), 'NFC_NFD_HarfBuzz': 'pass',
              'outline_format': 'CFF; components flattened to Type 2 contours',
              'metrics': {'ascender': font['hhea'].ascent, 'descender': font['hhea'].descent,
                          'units_per_em': upm}, 'placements': placements}
    reports.mkdir(exist_ok=True)
    (reports / f'{output.stem}-build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'placements'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    placements, originals = build()
    validate_and_render(placements, originals)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_hash
    path = ROOT / 'manifest.json'
    manifest = json.loads(path.read_text())
    for item in (SHEET, REPORTS / 'source-Vietnamese-build.json'):
        manifest['sha256'][str(item.relative_to(ROOT))] = hashlib.sha256(item.read_bytes()).hexdigest()
    manifest['vietnamese_build'] = {'path': str(OUTPUT), 'sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}
    path.write_text(json.dumps(manifest, indent=2)+'\n')
