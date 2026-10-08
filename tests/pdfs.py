"""Тестовые PDF: изменённые копии примеров, XFA-признак, PDF без полей."""
import io

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

from imports.adapters import prepod_vnok_info_v2  # noqa: F401  (добавляет vendor в sys.path)
import acroform  # noqa: E402  (копия из проекта формы)


def with_values(source_bytes, values):
    """Копия PDF с другими значениями полей; внешний вид перерисовывается, как в prepare_copy."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source_bytes)))
    acroform.set_values(writer, values)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def with_xfa(source_bytes):
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source_bytes)))
    writer._root_object['/AcroForm'][NameObject('/XFA')] = TextStringObject('<xdp/>')
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def plain_pdf():
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
