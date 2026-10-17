"""Dựng OTF tạm từ CFF subset (fonts/*.bin) để render và kiểm tra.
Chạy:  python build_otf.py --run-dir artifacts/sample
"""
import argparse, glob, io, os
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont, newTable
from fontTools.pens.boundsPen import BoundsPen
from fontTools.agl import toUnicode
from fontTools.ttLib.tables._c_m_a_p import cmap_format_4
from fontTools.ttLib.tables._n_a_m_e import NameRecord
from fontTools.ttLib.tables.O_S_2f_2 import Panose
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.qu2cuPen import Qu2CuPen

def build(fn, out_dir="otf", out_name=None):
    with open(fn, 'rb') as source:
        data = source.read()
    if out_name and (os.path.basename(out_name) != out_name or "\\" in out_name or out_name in (".", "..")):
        raise ValueError("Invalid output font name")
    if data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        font = TTFont(io.BytesIO(data))
        if 'fvar' in font or 'CFF2' in font:
            raise ValueError('Variable fonts require an explicit static instance')
        name = out_name or font['name'].getDebugName(6) or os.path.basename(fn).split('.')[0]
        if 'glyf' in font:
            gs = font.getGlyphSet()
            charstrings = {}
            for glyph in font.getGlyphOrder():
                pen = T2CharStringPen(gs[glyph].width, gs)
                gs[glyph].draw(Qu2CuPen(pen, max_err=font['head'].unitsPerEm/1000, all_cubic=True))
                charstrings[glyph] = pen.getCharString()
            for table in ('glyf', 'loca', 'fpgm', 'prep', 'cvt ', 'gasp', 'DSIG'):
                if table in font:
                    del font[table]
            builder = FontBuilder(font=font, isTTF=False)
            builder.setupCFF(name, {'FamilyName': font['name'].getDebugName(1) or name,
                                  'FullName': font['name'].getDebugName(4) or name,
                                  'Weight': font['name'].getDebugName(2) or 'Regular',
                                  'ItalicAngle': font['post'].italicAngle}, charstrings, {})
            font.sfntVersion = 'OTTO'
            font['maxp'] = newTable('maxp')
            font['maxp'].tableVersion = 0x00005000
            font['maxp'].numGlyphs = len(charstrings)
            font['head'].indexToLocFormat = 0
            font['post'].formatType = 3.0
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, name+'.otf')
        font.save(out)
        return out, len(font.getGlyphOrder())
    cff = CFFFontSet(); cff.decompile(io.BytesIO(data), otFont=None)
    rawname = cff.fontNames[0]; name = rawname.split('+')[-1]
    td = cff[rawname]; order = list(td.charset)
    gs = td.CharStrings
    hmtx = {}
    for g in order:
        cs = gs[g]; bp = BoundsPen(gs); cs.draw(bp)
        w = getattr(cs, "width", None)
        if w is None: w = td.Private.defaultWidthX
        lsb = int(bp.bounds[0]) if bp.bounds else 0
        hmtx[g] = (int(w), lsb)
    bb = [int(v) for v in td.rawDict.get('FontBBox',[0,-200,1000,800])]
    font = TTFont(); font.sfntVersion = "OTTO"; font.setGlyphOrder(order)
    head = newTable("head"); head.tableVersion=1.0; head.fontRevision=1.0; head.checkSumAdjustment=0
    matrix = td.FontMatrix
    if matrix[0] != matrix[3] or matrix[1] or matrix[2] or matrix[0] <= 0:
        raise ValueError('Unsupported nonuniform CFF FontMatrix')
    head.magicNumber=0x5F0F3CF5; head.flags=0; head.unitsPerEm=round(1/matrix[0]); head.created=head.modified=0
    head.xMin,head.yMin,head.xMax,head.yMax = bb
    head.macStyle=0; head.lowestRecPPEM=8; head.fontDirectionHint=2; head.indexToLocFormat=0; head.glyphDataFormat=0
    font["head"]=head
    font["hmtx"]=newTable("hmtx"); font["hmtx"].metrics=hmtx
    hhea=newTable("hhea"); hhea.tableVersion=0x00010000
    hhea.ascent=bb[3]; hhea.descent=bb[1]; hhea.lineGap=0
    hhea.advanceWidthMax=max(w for w,_ in hmtx.values()); hhea.minLeftSideBearing=0; hhea.minRightSideBearing=0
    hhea.xMaxExtent=bb[2]; hhea.caretSlopeRise=1; hhea.caretSlopeRun=0; hhea.caretOffset=0
    hhea.reserved0=hhea.reserved1=hhea.reserved2=hhea.reserved3=0; hhea.metricDataFormat=0; hhea.numberOfHMetrics=len(order)
    font["hhea"]=hhea
    maxp=newTable("maxp"); maxp.tableVersion=0x00005000; maxp.numGlyphs=len(order); font["maxp"]=maxp
    cm={}
    for g in order:
        u = toUnicode(g)
        if len(u)==1 and "." not in g: cm[ord(u)]=g
    cmap=newTable("cmap"); cmap.tableVersion=0
    st=cmap_format_4(4); st.platformID=3; st.platEncID=1; st.language=0; st.cmap=cm
    cmap.tables=[st]; font["cmap"]=cmap
    nm=newTable("name"); nm.names=[]
    for nid,val in ((1,name),(2,"Regular"),(4,name),(6,name)):
        r=NameRecord(); r.nameID=nid; r.platformID=3; r.platEncID=1; r.langID=0x409; r.string=val; nm.names.append(r)
    font["name"]=nm
    post=newTable("post"); post.formatType=3.0; post.italicAngle=td.ItalicAngle; post.underlinePosition=-100; post.underlineThickness=50
    post.isFixedPitch=0; post.minMemType42=post.maxMemType42=post.minMemType1=post.maxMemType1=0
    font["post"]=post
    os2=newTable("OS/2"); os2.version=4; os2.xAvgCharWidth=500; os2.usWeightClass=400; os2.usWidthClass=5; os2.fsType=0
    for a in ("ySubscriptXSize","ySubscriptYSize","ySubscriptXOffset","ySubscriptYOffset","ySuperscriptXSize","ySuperscriptYSize","ySuperscriptXOffset","ySuperscriptYOffset","yStrikeoutSize","yStrikeoutPosition","sFamilyClass"): setattr(os2,a,0)
    os2.panose=Panose(); os2.ulUnicodeRange1=os2.ulUnicodeRange2=os2.ulUnicodeRange3=os2.ulUnicodeRange4=0
    os2.achVendID="NONE"; os2.fsSelection=0x40; os2.usFirstCharIndex=32; os2.usLastCharIndex=0xFFFF
    os2.sTypoAscender=bb[3]; os2.sTypoDescender=bb[1]; os2.sTypoLineGap=0
    os2.usWinAscent=bb[3]; os2.usWinDescent=abs(bb[1])
    os2.ulCodePageRange1=1; os2.ulCodePageRange2=0; os2.sxHeight=500; os2.sCapHeight=700
    os2.usDefaultChar=0; os2.usBreakChar=32; os2.usMaxContext=0
    font["OS/2"]=os2
    cfft=newTable("CFF "); cfft.cff=cff; font["CFF "]=cfft
    os.makedirs(out_dir, exist_ok=True); out=os.path.join(out_dir, f"{out_name or name}.otf"); font.save(out); return out, len(order)

if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=".", help="Thư mục chứa artifact của một lần chạy")
    args = parser.parse_args()
    for fn in sorted(glob.glob(os.path.join(args.run_dir, "fonts", "*.bin"))):
        try: print(build(fn, os.path.join(args.run_dir, "otf")))
        except Exception as e: print("FAIL", fn, repr(e))
