"""Measure each font and fit accent templates in that font's own units."""
import json
from math import hypot, radians, tan, atan, degrees
from pathlib import Path
from statistics import median

from fontTools.pens.basePen import BasePen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

from draw_marks import bounds, centered, outline, transformed


TEMPLATES = Path(__file__).parent/'profiles/templates.json'


class FlattenPen(BasePen):
    def __init__(self):
        super().__init__(None)
        self.contours = []

    def _moveTo(self, point):
        self.points = [point]

    def _lineTo(self, point):
        self.points.append(point)

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        for step in range(1, 33):
            t = step/32
            self.points.append(tuple((1-t)**3*p0[k]+3*(1-t)**2*t*p1[k]+3*(1-t)*t*t*p2[k]+t**3*p3[k] for k in (0, 1)))

    def _closePath(self):
        self.contours.append(self.points)


def contours(drawing):
    result, part = [], RecordingPen()
    for operation, points in drawing.value:
        getattr(part, operation)(*points)
        if operation == 'closePath':
            result.append(part)
            part = RecordingPen()
    return result


def scanline(drawing, y):
    """Return filled x intervals using nonzero winding, including overlapping contours."""
    pen = FlattenPen()
    drawing.replay(pen)
    events = []
    for points in pen.contours:
        for p, q in zip(points, points[1:]+points[:1]):
            if min(p[1], q[1]) <= y < max(p[1], q[1]):
                x = p[0]+(q[0]-p[0])*(y-p[1])/(q[1]-p[1])
                events.append((x, 1 if q[1] > p[1] else -1))
    intervals, winding, start = [], 0, None
    for x, delta in sorted(events):
        previous = winding
        winding += delta
        if previous == 0 and winding:
            start = x
        elif previous and winding == 0 and x > start:
            intervals.append((start, x))
    return intervals


def weight_adjust(drawing, delta):
    """Offset closed template polygons a small amount to match measured stem weight."""
    if abs(delta) < .5:
        return drawing
    pen, result = FlattenPen(), RecordingPen()
    drawing.replay(pen)
    for points in pen.contours:
        points = [p for i, p in enumerate(points) if p != points[i-1]]
        area = sum(p[0]*q[1]-q[0]*p[1] for p, q in zip(points, points[1:]+points[:1]))
        sign = 1 if area > 0 else -1
        normals = []
        for p, q in zip(points, points[1:]+points[:1]):
            length = hypot(q[0]-p[0], q[1]-p[1])
            normals.append((sign*(q[1]-p[1])/length, -sign*(q[0]-p[0])/length))
        offset = []
        for i, p in enumerate(points):
            a, b = normals[i-1], normals[i]
            factor = delta/max(.5, 1+a[0]*b[0]+a[1]*b[1])
            offset.append((p[0]+factor*(a[0]+b[0]), p[1]+factor*(a[1]+b[1])))
        result.moveTo(offset[0])
        for point in offset[1:]:
            result.lineTo(point)
        result.closePath()
    return result


def calibrate(source, templates_path=TEMPLATES):
    templates = json.loads(templates_path.read_text())
    reference = templates['reference']
    with TTFont(source) as font:
        if 'CFF ' not in font:
            raise ValueError('Calibration requires a static CFF font')
        cmap, gs = font.getBestCmap() or {}, font.getGlyphSet()
        upm = font['head'].unitsPerEm
        drawings = {}
        for code, name in cmap.items():
            pen = RecordingPen()
            gs[name].draw(pen)
            if bounds(pen):
                drawings[chr(code)] = pen
        if not cmap:
            raise ValueError('No mapped Unicode; cannot infer glyph semantics')
        lower = [bounds(drawings[c])[3] for c in 'aexonuv' if c in drawings]
        upper = [bounds(drawings[c])[3] for c in 'HEIOAUY' if c in drawings]
        xheight = median(lower) if lower else upm*.45
        capheight = median(upper) if upper else upm*.66
        round_width = bounds(drawings['o'])[2]-bounds(drawings['o'])[0] if 'o' in drawings else xheight*.97
        strokes = []
        for c in 'uInHo':
            if c not in drawings:
                continue
            b = bounds(drawings[c])
            for left, right in scanline(drawings[c], b[1]+(b[3]-b[1])*.53):
                width = right-left
                if upm*.015 < width < upm*.25:
                    strokes.append(width)
        stem = median(strokes) if strokes else upm*.085
        top = font['CFF '].cff.topDictIndex[0]
        full_name = getattr(top, 'FullName', None) or font['name'].getDebugName(4) or source.stem
        angle = float(top.ItalicAngle)
        angle_source = 'native'
        if not angle and any(label in full_name.lower() for label in ('italic', 'oblique')):
            angles = []
            for c in 'IHld':
                if c not in drawings:
                    continue
                b = bounds(drawings[c])
                bottom = max(b[1], xheight) if c == 'd' else b[1]
                y1, y2 = bottom+(b[3]-bottom)*.2, bottom+(b[3]-bottom)*.8
                a, z = scanline(drawings[c], y1), scanline(drawings[c], y2)
                if a and z and y2 > y1:
                    angles.append(-degrees(atan((z[0][0]-a[0][0])/(y2-y1))))
            angle = median(angles) if angles else -12
            angle_source = 'stem measurement' if angles else 'italic name fallback (-12 degrees)'
        shear = tan(radians(-angle))
        sx, sy = round_width/reference['round_width'], xheight/reference['x_height']
        # shortcut: template offsets approximate optical weight; review for publication use.
        delta = max(-xheight*.02, min(xheight*.035, .18*(stem-reference['stem']*min(sx, sy))))
        marks = {}
        for name, commands in templates['marks'].items():
            drawing = transformed(outline(commands), (sx, 0, 0, sy, 0, 0))
            drawing = centered(weight_adjust(drawing, delta))
            marks[name] = transformed(drawing, (1, 0, shear, 1, 0, 0))
        accent_source = 'scaled template'
        for c in ('\u0301', '\u00b4', 'é', 'á', 'ó', 'ú', 'í', 'ý', 'É', 'Á'):
            if c not in drawings:
                continue
            drawing = drawings[c]
            if c not in ('\u0301', '\u00b4'):
                import unicodedata as ud
                base = ud.normalize('NFD', c)[0]
                if base not in drawings:
                    continue
                pieces = [p for p in contours(drawing) if bounds(p)[1] > bounds(drawings[base])[3]]
                if not pieces:
                    continue
                drawing = RecordingPen()
                for piece in pieces:
                    piece.replay(drawing)
            marks['acute'] = centered(drawing)
            accent_source = f'native U+{ord(c):04X}'
            break
        # Mirroring in the upright frame retains the font's italic slant.
        upright = transformed(marks['acute'], (1, 0, -shear, 1, 0, 0))
        marks['grave'] = centered(transformed(upright, (-1, 0, shear, 1, 0, 0)))
        if '.' in drawings:
            marks['dotbelow'] = centered(transformed(drawings['.'], (.65, 0, 0, .65, 0, 0)))
        additions = {}
        horn = outline(templates['horn'])
        for c in 'ouOU':
            if c not in drawings:
                continue
            b = bounds(drawings[c])
            height = b[3]-b[1]
            if c.lower() == 'o':
                y = b[3]-.085*height
                intervals = scanline(drawings[c], y)
                if not intervals:
                    raise ValueError(f'Cannot find horn attachment on {c}')
                x = intervals[-1][1]-.35*stem
            else:
                intervals = scanline(drawings[c], b[1]+height*.75)
                if not intervals:
                    raise ValueError(f'Cannot find horn attachment on {c}')
                x, y = intervals[-1][1]-.35*stem, b[3]-.04*height
            scale = sy*(1.08 if c.isupper() else 1)
            part = weight_adjust(transformed(horn, (scale, 0, 0, scale, 0, 0)), delta)
            # Shear only the new outline; the source letter is already slanted.
            additions[c] = transformed(part, (1, 0, shear, 1, x, y))
        for c in 'dD':
            if c not in drawings:
                continue
            b = bounds(drawings[c])
            y = (xheight+(b[3]-xheight)*.42) if c == 'd' else b[3]*.5
            intervals = scanline(drawings[c], y)
            if not intervals:
                raise ValueError(f'Cannot find crossbar stem on {c}')
            left, right = intervals[-1] if c == 'd' else intervals[0]
            thickness = .45*stem
            left -= (1.2 if c == 'd' else 1.05)*stem
            right += (.75 if c == 'd' else 1.5)*stem
            additions[c] = outline([
                ('moveTo', ((left, y-thickness/2),)),
                ('lineTo', ((right, y-thickness/2),)),
                ('lineTo', ((right+shear*thickness, y+thickness/2),)),
                ('lineTo', ((left+shear*thickness, y+thickness/2),)), ('closePath', ()),
            ])
        native_weight = getattr(top, 'Weight', None)
        weight = str(native_weight or full_name).lower()
        weight_class = next((number for label, number in [('semibold', 600), ('demi', 600),
                            ('bold', 700), ('black', 900), ('light', 300), ('medium', 500)]
                            if label in weight), 400)
        weight_name = str(native_weight or {300: 'Light', 400: 'Regular', 500: 'Medium', 600: 'Semibold', 700: 'Bold', 900: 'Black'}[weight_class])
        condensed = 'cond' in full_name.lower()
        style = (weight_name+' ' if weight_class != 400 else '')+('Condensed ' if condensed else '')+('Italic' if angle else '')
        style = style.strip() or 'Regular'
        return {'source': str(source), 'units_per_em': upm, 'x_height': xheight,
                'cap_height': capheight, 'stem': stem, 'round_width': round_width,
                'italic_angle': angle, 'angle_source': angle_source, 'weight_class': weight_class, 'width_class': 3 if condensed else 5, 'style': style,
                'weight_name': weight_name, 'gap': max(upm*.025, xheight*.098),
                'cap_scale': .85, 'stack_scale': .8, 'acute_source': accent_source,
                'missing_bases': [c for c in 'AEIOUYaeiouydD' if c not in drawings],
                'marks': {n: {'bounds': bounds(p), 'commands': p.value} for n, p in marks.items()},
                'glyphs': {n: {'bounds': bounds(p), 'commands': p.value} for n, p in additions.items()}}


def compose(font, base, shape, tone, marks, additions, calibration):
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    drawing = RecordingPen()
    gs[cmap[ord(base)]].draw(drawing)
    if base == 'i' and tone and tone != 'dotbelow':
        stem = RecordingPen()
        for part in contours(drawing):
            if bounds(part)[1] < calibration['x_height']*.9:
                part.replay(stem)
        if not bounds(stem):
            raise ValueError('Cannot separate the dot from i')
        drawing = stem
    box = bounds(drawing)
    center, gap = (box[0]+box[2])/2, calibration['gap']
    parts, detail = [('base', drawing)], []
    scale = calibration['cap_scale'] if base.isupper() else 1
    y = box[3]+gap
    if shape in ('horn', 'stroke'):
        addition = additions[base]
        parts.append((shape, addition))
        y = max(y, bounds(addition)[3]+gap*.82)
    elif shape:
        matrix = (scale, 0, 0, scale, center, y)
        addition = transformed(marks[shape], matrix)
        parts.append((shape, addition))
        detail.append({'mark': shape, 'transform': matrix})
        y = bounds(addition)[3]+gap*.68
    if tone:
        ts = scale*(calibration['stack_scale'] if shape in ('circumflex', 'breve') else 1)
        if tone == 'dotbelow':
            ts = scale
            y = min(box[1], 0)-gap-bounds(marks[tone])[3]*ts
        shift = {'acute': .089, 'grave': -.0445}.get(tone, 0)*calibration['x_height']
        matrix = (ts, 0, 0, ts, center+shift, y)
        addition = transformed(marks[tone], matrix)
        if tone == 'dotbelow':
            assert bounds(addition)[3] < box[1]
        else:
            assert bounds(addition)[1] >= max(bounds(p)[3] for _, p in parts)
        parts.append((tone, addition))
        detail.append({'mark': tone, 'transform': matrix})
    combined = RecordingPen()
    for _, part in parts:
        part.replay(combined)
    width = gs[cmap[ord(base)]].width
    if shape == 'horn':
        width = max(width, bounds(combined)[2]+calibration['units_per_em']*.025)
    return combined, parts, detail, round(width)
