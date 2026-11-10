"""Turn an uploaded file into Markdown text.

PDF, DOCX and HTML go through docling, which keeps headings, lists and tables.
Plain text and Markdown are already text and are decoded as-is. Set
DOCUMENT_PARSER=basic to use the small pure-Python parsers instead (also the
automatic fallback when docling cannot handle a file).
"""

import io
import logging
import threading
from pathlib import PurePath

from app.config import get_settings

logger = logging.getLogger(__name__)

MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
}
ALLOWED_EXTENSIONS = set(MIME_TYPES)
TEXT_EXTENSIONS = {".txt", ".md"}


class IngestionError(Exception):
    """A problem with the file itself; the message is shown to the user."""


def extension_of(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def mime_type_of(filename: str) -> str:
    return MIME_TYPES.get(extension_of(filename), "application/octet-stream")


def parse_document(filename: str, data: bytes) -> str:
    ext = extension_of(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise IngestionError(f"Unsupported file type: {ext or 'none'}")
    if ext in TEXT_EXTENSIONS:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestionError("File is not valid UTF-8 text") from exc

    if get_settings().document_parser == "docling":
        try:
            return _parse_with_docling(filename, data)
        except ImportError:
            logger.warning("docling is not installed; using the basic parsers")
        except Exception as exc:
            logger.warning("docling failed on %s (%s); trying the basic parser", filename, exc)
    return _parse_basic(filename, ext, data)


# --- docling ----------------------------------------------------------------

_converter = None
_converter_lock = threading.Lock()


def _get_converter():
    """One shared converter: importing docling and loading its models is slow."""
    global _converter
    with _converter_lock:
        if _converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            # OCR is off: scanned images are out of scope, and it keeps parsing fast.
            pdf = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
            _converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf)}
            )
        return _converter


def _parse_with_docling(filename: str, data: bytes) -> str:
    from docling.datamodel.base_models import DocumentStream

    stream = DocumentStream(name=PurePath(filename).name, stream=io.BytesIO(data))
    result = _get_converter().convert(stream)
    return result.document.export_to_markdown()


# --- basic parsers ------------------------------------------------------------


def _parse_basic(filename: str, ext: str, data: bytes) -> str:
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        if ext == ".docx":
            return _docx_to_markdown(data)
        if ext in {".html", ".htm"}:
            return _html_to_text(data)
    except IngestionError:
        raise
    except Exception as exc:  # the parsers raise many unrelated types
        kind = ext.lstrip(".").upper()
        raise IngestionError(f"Could not read {kind} file: {exc}") from exc
    raise IngestionError(f"Unsupported file type: {ext}")


def _docx_to_markdown(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    parts: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style is not None else "") or ""
        if style.startswith("Heading"):
            level = style.removeprefix("Heading").strip()
            parts.append("#" * (int(level) if level.isdigit() else 1) + " " + text)
        elif style == "Title":
            parts.append("# " + text)
        else:
            parts.append(text)
    for table in document.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if rows:
            lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _html_to_text(data: bytes) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    for level in range(1, 7):
        for heading in soup.find_all(f"h{level}"):
            heading.insert_before("\n\n" + "#" * level + " ")
            heading.insert_after("\n\n")
    lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    # A heading marker and its text land on separate lines; join them.
    text = "\n".join(out)
    for level in range(6, 0, -1):
        text = text.replace("#" * level + "\n", "#" * level + " ")
    return text.strip()
