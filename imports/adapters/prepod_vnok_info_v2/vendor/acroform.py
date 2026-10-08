"""Minimal AcroForm writer: no XFA, no JavaScript, no buttons.

Every field gets an appearance stream (/AP), and the full TrueType font is
embedded in /AcroForm/DR so viewers can redraw any Cyrillic text typed later.
"""
from hashlib import sha256
from io import BytesIO
import re

from fontTools import subset
from fontTools.ttLib import TTFont
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject,
                           NameObject, NumberObject, TextStringObject)

FONT_KEY = 'Serif'
FF_READ_ONLY = 1
FF_REQUIRED = 2
FF_MULTILINE = 1 << 12
FF_DO_NOT_SPELL_CHECK = 1 << 22
PRINT_FLAG = 4
HIDDEN_FLAG = 2


def stream(writer, content, **entries):
    item = DecodedStreamObject()
    item.set_data(content.encode('latin-1') if isinstance(content, str) else content)
    item = item.flate_encode()
    for key, value in entries.items():
        item[NameObject('/' + key)] = value
    return writer._add_object(item)


def number(value):
    return f'{value:.2f}'.rstrip('0').rstrip('.')


class EmbeddedFont:
    """Glyph metrics and encoding for an Identity-H Type0 font."""

    def __init__(self, data):
        self.data = data
        font = TTFont(BytesIO(data))
        order = font.getGlyphOrder()
        gid = {name: index for index, name in enumerate(order)}
        self.cmap = {code: gid[name] for code, name in font.getBestCmap().items()}
        scale = 1000 / font['head'].unitsPerEm
        self.widths = [round(font['hmtx'][name][0] * scale) for name in order]
        self.ascent = round(font['hhea'].ascent * scale)
        self.descent = round(font['hhea'].descent * scale)
        head = font['head']
        self.bbox = [round(v * scale) for v in (head.xMin, head.yMin, head.xMax, head.yMax)]
        self.cap_height = round(getattr(font['OS/2'], 'sCapHeight', 0) * scale) or self.ascent
        self.postscript_name = font['name'].getDebugName(6)
        self.glyph_count = len(order)

    def glyphs(self, text):
        return [self.cmap.get(ord(char), 0) for char in text]

    def width(self, text, size):
        return sum(self.widths[g] for g in self.glyphs(text)) * size / 1000

    def encode(self, text):
        return '<' + ''.join(f'{g:04X}' for g in self.glyphs(text)) + '>'

    def wrap(self, text, width, size):
        """Greedy word wrap; overlong words are split by characters."""
        lines = []
        for paragraph in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            line = ''
            for word in re.split(r'(\s+)', paragraph.replace('\t', '    ')):
                candidate = line + word
                if self.width(candidate, size) <= width or not line.strip():
                    line = candidate
                else:
                    lines.append(line.rstrip())
                    line = word.lstrip()
                while self.width(line, size) > width and len(line) > 1:
                    cut = len(line) - 1
                    while cut > 1 and self.width(line[:cut], size) > width:
                        cut -= 1
                    lines.append(line[:cut])
                    line = line[cut:]
            lines.append(line.rstrip())
        return lines

    def to_unicode(self):
        reverse = {}
        for code, glyph in sorted(self.cmap.items()):
            reverse.setdefault(glyph, code)
        entries = [f'<{g:04X}> <{chr(c).encode("utf-16-be").hex().upper()}>' for g, c in sorted(reverse.items())]
        chunks = ''.join(f'{len(entries[i:i + 100])} beginbfchar\n' + '\n'.join(entries[i:i + 100]) + '\nendbfchar\n'
                         for i in range(0, len(entries), 100))
        return ('/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n'
                '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
                '/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n'
                '1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n' + chunks +
                'endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n')

    def subset_data(self, chars):
        """Subset that keeps glyph IDs, for static page text only (never for field fonts)."""
        options = subset.Options()
        options.retain_gids = True
        options.notdef_outline = True
        options.name_IDs = ['*']
        font = TTFont(BytesIO(self.data))
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes={ord(c) for c in chars})
        subsetter.subset(font)
        output = BytesIO()
        font.save(output)
        return output.getvalue()

    def add_to(self, writer, chars=None):
        """Embed the full font, or a GID-preserving subset when chars is given."""
        data, name = self.data, self.postscript_name
        if chars is not None:
            data = self.subset_data(chars)
            tag = ''.join(chr(65 + b % 26) for b in sha256(''.join(sorted(chars)).encode()).digest()[:6])
            name = f'{tag}+{name}'
        name = NameObject('/' + name)
        file = stream(writer, data, Length1=NumberObject(len(data)))
        descriptor = writer._add_object(DictionaryObject({
            NameObject('/Type'): NameObject('/FontDescriptor'),
            NameObject('/FontName'): name,
            NameObject('/Flags'): NumberObject(32),
            NameObject('/FontBBox'): ArrayObject(NumberObject(v) for v in self.bbox),
            NameObject('/ItalicAngle'): NumberObject(0),
            NameObject('/Ascent'): NumberObject(self.ascent),
            NameObject('/Descent'): NumberObject(self.descent),
            NameObject('/CapHeight'): NumberObject(self.cap_height),
            NameObject('/StemV'): NumberObject(80),
            NameObject('/FontFile2'): file,
        }))
        descendant = writer._add_object(DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/CIDFontType2'),
            NameObject('/BaseFont'): name,
            NameObject('/CIDSystemInfo'): DictionaryObject({
                NameObject('/Registry'): TextStringObject('Adobe'),
                NameObject('/Ordering'): TextStringObject('Identity'),
                NameObject('/Supplement'): NumberObject(0)}),
            NameObject('/FontDescriptor'): descriptor,
            NameObject('/W'): ArrayObject([NumberObject(0), ArrayObject(NumberObject(w) for w in self.widths)]),
            NameObject('/CIDToGIDMap'): NameObject('/Identity'),
        }))
        return writer._add_object(DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type0'),
            NameObject('/BaseFont'): name,
            NameObject('/Encoding'): NameObject('/Identity-H'),
            NameObject('/DescendantFonts'): ArrayObject([descendant]),
            NameObject('/ToUnicode'): stream(writer, self.to_unicode()),
        }))


def text_appearance(writer, font, font_ref, width, height, value, size, multiline, pad=2.5):
    ops = ['/Tx BMC', 'q', f'1 1 {number(width - 2)} {number(height - 2)} re W n']
    if value:
        ops += ['BT', f'/{FONT_KEY} {number(size)} Tf', '0 g']
        if multiline:
            leading = size * 1.15
            lines = font.wrap(value, width - 2 * pad, size)[:int(height / leading) + 1]
            top = height - pad - font.ascent * size / 1000
            ops += [f'{number(leading)} TL', f'{number(pad)} {number(top)} Td']
            ops += [f'{font.encode(line)} Tj T*' for line in lines]
        else:
            glyph_height = (font.ascent - font.descent) * size / 1000
            baseline = (height - glyph_height) / 2 - font.descent * size / 1000
            ops += [f'{number(pad)} {number(baseline)} Td', f'{font.encode(" ".join(value.splitlines()))} Tj']
        ops.append('ET')
    ops += ['Q', 'EMC']
    return appearance(writer, width, height, '\n'.join(ops), {FONT_KEY: font_ref})


def appearance(writer, width, height, content, fonts):
    resources = DictionaryObject()
    if fonts:
        resources[NameObject('/Font')] = DictionaryObject({NameObject('/' + k): v for k, v in fonts.items()})
    return stream(writer, content, Type=NameObject('/XObject'), Subtype=NameObject('/Form'),
                  BBox=ArrayObject([NumberObject(0), NumberObject(0), FloatObject(width), FloatObject(height)]),
                  Resources=resources)


def font_size(widget):
    match = re.search(r'([\d.]+)\s+Tf', str(widget.get('/DA', '')))
    return float(match.group(1)) if match and float(match.group(1)) > 0 else 10.0


def iter_terminal_fields(fields, prefix=''):
    """Yield (qualified name, field dict) for leaf fields."""
    for ref in fields:
        node = ref.get_object()
        name = prefix + str(node.get('/T', ''))
        kids = node.get('/Kids')
        if kids and '/T' in kids[0].get_object():
            yield from iter_terminal_fields(kids, name + '.')
        else:
            yield name, node


def field_type(node):
    while node is not None:
        if '/FT' in node:
            return node['/FT']
        node = node.get('/Parent')
        node = node.get_object() if node is not None else None
    return None


def set_values(writer, values):
    """Set field values and regenerate appearances with the font from /DR."""
    acroform = writer.root_object['/AcroForm']
    font_ref = acroform['/DR']['/Font'].raw_get('/' + FONT_KEY)
    font_data = font_ref.get_object()['/DescendantFonts'][0].get_object()['/FontDescriptor']['/FontFile2'].get_data()
    font = EmbeddedFont(font_data)
    fields = dict(iter_terminal_fields(acroform['/Fields']))
    unknown = set(values) - set(fields)
    if unknown:
        raise KeyError(f'Неизвестные поля: {", ".join(sorted(unknown))}')
    for name, value in values.items():
        field = fields[name]
        rect = [float(v) for v in field['/Rect']]
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        if field_type(field) != '/Tx':
            raise ValueError(f'Поле {name} не текстовое.')
        text = '' if value is None else str(value)
        field[NameObject('/V')] = TextStringObject(text)
        multiline = bool(int(field.get('/Ff', 0)) & FF_MULTILINE)
        field[NameObject('/AP')] = DictionaryObject({NameObject('/N'): text_appearance(
            writer, font, font_ref, width, height, text, font_size(field), multiline)})
