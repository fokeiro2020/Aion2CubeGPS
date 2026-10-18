"""Fetch upstream repository assets/source for local review, WITHOUT executing them.

No remote code is imported by Cube Finder. Downloads the GitHub archives of two
public projects, extracts selected paths, and records provenance and checksums.

License notes:
  - dr89mh/aion2-cube-radar: GPL-3.0 (retain its original LICENSE).
  - benhighlanderr/Aion2-Hidden-Cube-Radar: no LICENSE observed on 2026-10-17;
    code is reference-only; ask author for permission before redistribution.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZipFile, BadZipFile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DESTINATION = ROOT / "upstream_sources"
SOURCES = (
    ("benhighlanderr", "Aion2-Hidden-Cube-Radar", "main", "license not found; reference only"),
    ("dr89mh", "aion2-cube-radar", "main", "GPL-3.0; source and attribution required for redistributed derivatives"),
)
ARCHIVE_CAP = 65 * 1024 * 1024
FILE_CAP = 16 * 1024 * 1024
TOTAL_EXTRACT_CAP = 140 * 1024 * 1024
EXT_SKIP = {".exe", ".dll", ".msi", ".pdb", ".pcap", ".pcapng", ".zip", ".7z", ".rar", ".mp4"}
FOLDER_SKIP = {".git", ".github", "bin", "obj", "node_modules", "__pycache__", "fixtures"}


def zip_member_destination(name: str, repository: str):
    """Return a relative safe path, or None. No paths escape repo folder."""
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("..", "") for part in path.parts):
        return None
    parts = path.parts
    if len(parts) < 2:
        return None
    rel = PurePosixPath(*parts[1:])  # ZIP normally has repo-branch/ prefix
    if any(seg in FOLDER_SKIP for seg in rel.parts) or rel.suffix.lower() in EXT_SKIP:
        return None
    if len(rel.parts) == 0:
        return None
    return Path(*rel.parts)


def fetch_zip(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "Aion2CubeFinder-SourceSync/1.0", "Accept": "application/zip"})
    with urlopen(req, timeout=45) as response:
        data = response.read(ARCHIVE_CAP + 1)
    if len(data) > ARCHIVE_CAP:
        raise ValueError("GitHub ZIP exceeds configured 65 MB download limit")
    return data


def unpack_safe(data: bytes, staging: Path, repository: str) -> list[dict]:
    total = 0
    files = []
    with ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Reject symlinks and non regular files. GitHub archives are expected to be files.
            unix_type = (info.external_attr >> 16) & 0o170000
            if unix_type == 0o120000:
                continue
            rel = zip_member_destination(info.filename, repository)
            if rel is None or info.file_size > FILE_CAP:
                continue
            total += info.file_size
            if total > TOTAL_EXTRACT_CAP:
                raise ValueError("Extracted content exceeds size limit")
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with zf.open(info) as src, target.open("wb") as out:
                while block := src.read(512 * 1024):
                    out.write(block)
                    digest.update(block)
            files.append({"path": rel.as_posix(), "bytes": info.file_size, "sha256": digest.hexdigest()})
    return files


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    failures = 0
    for owner, repo, branch, license_note in SOURCES:
        url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"
        print(f"\nFetching {owner}/{repo} ...", flush=True)
        tmp = Path(tempfile.mkdtemp(prefix="cube-sync-", dir=DESTINATION))
        try:
            data = fetch_zip(url)
            records = unpack_safe(data, tmp, repo)
            manifest = {
                "source_url": f"https://github.com/{owner}/{repo}",
                "archive_url": url,
                "branch": branch,
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "archive_sha256": hashlib.sha256(data).hexdigest(),
                "license_note": license_note,
                "files": records,
                "excluded": "archives, executables, captures, binary dependencies, build folders and fixtures",
            }
            (tmp / "FETCH_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            if owner == "dr89mh" and not (tmp / "LICENSE").exists():
                raise ValueError("Expected GPL-3.0 LICENSE was not in the download")
            folder = DESTINATION / f"{owner}_{repo}"
            if folder.exists():
                shutil.rmtree(folder)
            tmp.rename(folder)
            print(f"Saved {len(records)} files in {folder}")
        except Exception as exc:
            failures += 1
            print(f"ERROR downloading {owner}/{repo}: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
