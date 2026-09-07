from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

from pypdf import PdfReader

from core.errors import ValidationError


MAX_RESUME_BYTES = 5 * 1024 * 1024
MAX_RESUME_CHARS = 500_000
MAX_PDF_PAGES = 80


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError("TXT 编码无法识别，请转换为 UTF-8 后重试")


def _extract_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            try:
                if reader.decrypt("") == 0:
                    raise ValidationError("PDF 已加密，无法提取文本")
            except Exception as exc:
                if isinstance(exc, ValidationError):
                    raise
                raise ValidationError("PDF 已加密，无法提取文本") from None
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValidationError(f"PDF 页数不能超过 {MAX_PDF_PAGES} 页")
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("PDF 无法读取或文件已损坏") from exc
    if not text.strip():
        raise ValidationError("PDF 未提取到文本；扫描件请先进行 OCR")
    return text


def extract_resume(filename: str, content: bytes) -> dict[str, str | int]:
    name = Path(str(filename or "")).name
    suffix = Path(name).suffix.lower()
    if suffix not in {".txt", ".pdf"}:
        raise ValidationError("当前简历只支持 TXT 或 PDF")
    if not content:
        raise ValidationError("上传文件为空")
    if len(content) > MAX_RESUME_BYTES:
        raise ValidationError("简历文件不能超过 5 MB")
    text = _decode_text(content) if suffix == ".txt" else _extract_pdf(content)
    text = re.sub(r"\x00", "", text).strip()
    if len(text) > MAX_RESUME_CHARS:
        raise ValidationError("提取后的简历文本过长")
    import hashlib

    return {
        "filename": name,
        "file_type": suffix[1:],
        "text": text,
        "sha256": hashlib.sha256(content).hexdigest(),
        "character_count": len(text),
    }
