import mimetypes
import pathlib


def extension_from_input(filename: str | None, content_type: str | None):
    if filename:
        ext = pathlib.Path(filename).suffix.lstrip(".")
        if ext:
            return ext
    if content_type:
        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            return guessed.lstrip(".")
    return "jpg"
