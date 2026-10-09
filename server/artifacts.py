"""Collect small learner outputs after their entire process tree has ended."""

import mimetypes
import os
import stat
from collections import deque
from dataclasses import dataclass
from pathlib import Path

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".log", ".html", ".css"}
SKIP_DIRECTORIES = {"__pycache__", ".pytest_cache", ".git", "node_modules"}
MAX_ARTIFACT_BYTES = 1_048_576


@dataclass(frozen=True)
class Artifact:
    data: bytes
    mime: str


def collect_artifacts(directory, originals):
    root = Path(directory).resolve()
    pending = deque([root])
    output = {}
    total = 0
    inspected = 0
    while pending and inspected < 500 and len(output) < 20:
        current = pending.popleft()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            inspected += 1
            if inspected > 500 or len(output) >= 20:
                break
            try:
                info = entry.stat(follow_symlinks=False)
                # Windows junctions and other reparse points are excluded,
                # including points whose final target happens to remain inside.
                if (entry.is_symlink() or getattr(info, "st_file_attributes", 0)
                        & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                    continue
                path = Path(entry.path)
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    continue
                if stat.S_ISDIR(info.st_mode):
                    if entry.name not in SKIP_DIRECTORIES and not entry.name.startswith("."):
                        pending.append(resolved)
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARTIFACT_BYTES - total:
                    continue
                extension = path.suffix.lower()
                if extension not in TEXT_EXTENSIONS | {".png", ".jpg", ".jpeg"}:
                    continue
                name = resolved.relative_to(root).as_posix()
                data = resolved.read_bytes()
                if data == originals.get(name):
                    continue
                if len(data) > MAX_ARTIFACT_BYTES - total:
                    continue
                if extension == ".png":
                    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                        continue
                    mime = "image/png"
                elif extension in {".jpg", ".jpeg"}:
                    if not data.startswith(b"\xff\xd8"):
                        continue
                    mime = "image/jpeg"
                else:
                    data.decode("utf-8")  # only valid UTF-8 plain text
                    mime = mimetypes.guess_type(name)[0] or "text/plain"
                output[name] = Artifact(data, mime)
                total += len(data)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
    return output
