"""The thumbnail a file gets when keepgram sends it as a file: a picture of its
kind (assets/make_thumbs.py draws them) instead of Telegram's blank file icon.
Photos sent as photos and videos sent as videos show as they always do - they
never get one.

config "thumbnails":
    logo   every file keepgram sends as a file gets its kind's picture (default)
    own    a file keeps a thumbnail it already has (a copied video's frame);
           the rest get their kind's picture
    none   no pictures from keepgram"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

_EXT = {
    "video": "mkv mp4 m4v avi mov webm ts m2ts mts flv wmv mpg mpeg 3gp ogv vob rmvb",
    "audio": "mp3 flac m4a aac ogg oga opus wav wma alac aiff ape mka",
    "image": "jpg jpeg png gif webp heic heif bmp tif tiff svg avif raw cr2 nef arw dng psd",
    "archive": "zip rar 7z tar gz tgz bz2 xz zst lz4 iso img dmg cab",
    "document": "pdf doc docx odt rtf txt md epub mobi azw3 djvu xls xlsx ods csv ppt pptx odp json xml html srt "
                "ass vtt",
    "app": "apk apks xapk aab exe msi deb rpm appimage ipa jar bat sh",
}
_BY_EXT = {ext: kind for kind, exts in _EXT.items() for ext in exts.split()}
_PART = re.compile(r"\.\d{3,}$")
KINDS = (*_EXT, "part", "other")


def kind_of(name: str, mime: str | None = None) -> str:
    """video | audio | image | archive | document | app | part | other."""
    name = (name or "").lower()
    if _PART.search(name):
        return "part"
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in _BY_EXT:
        return _BY_EXT[ext]
    mime = mime or mimetypes.guess_type(name)[0] or ""
    top = mime.split("/")[0]
    if top in ("video", "audio", "image"):
        return top
    if mime == "application/pdf" or top == "text":
        return "document"
    return "other"


def logo(name: str, mime: str | None = None) -> str:
    """The path of the picture for this file."""
    return str(HERE / f"{kind_of(name, mime)}.jpg")


def mode(cfg: dict) -> str:
    value = cfg.get("thumbnails", "logo")
    return value if value in ("logo", "own", "none") else "logo"
