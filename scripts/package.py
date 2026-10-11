#!/usr/bin/env python3
"""Package and verify a tagged FeROS Sources catalog (Python 3.11+ stdlib)."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'dist' / 'site'
DIST = ROOT / 'dist'


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package(tag: str) -> None:
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Expected a vMAJOR.MINOR.PATCH tag')
    version = tomllib.loads((ROOT / 'src/catalog.toml').read_text(encoding='utf-8'))['catalog_version']
    if tag != f'v{version}':
        raise ValueError(f'{tag} does not match catalog version {version}')
    commit = git('rev-parse', 'HEAD')
    if git('rev-parse', f'{tag}^{{commit}}') != commit:
        raise ValueError('Release tag does not point to checkout')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Tracked sources have uncommitted changes')
    if not SITE.is_dir():
        raise ValueError('Missing dist/site; run build_site.py first')
    catalog = tomllib.loads((SITE / 'catalog.toml').read_text(encoding='utf-8'))
    if catalog['catalog_version'] != version:
        raise ValueError('Built catalog version mismatch')
    expected = {'repository.toml', 'catalog.toml', 'site.json'}
    expected.update(d['manifest'] for d in catalog.get('devices', []))
    actual = {p.relative_to(SITE).as_posix() for p in SITE.rglob('*') if p.is_file()}
    if actual != expected | {'index.html', '.nojekyll'}:
        raise ValueError(f'Unexpected site contents: missing={expected - actual}, extra={actual - expected - {"index.html", ".nojekyll"}}')
    import json
    metadata = json.loads((SITE / 'site.json').read_text(encoding='utf-8'))
    if metadata['commit'] != commit:
        raise ValueError('site.json commit does not match tag')
    listed = {f['path']: f for f in metadata['files']}
    if set(listed) != expected - {'site.json'}:
        raise ValueError('site.json file inventory mismatch')
    for path in expected - {'site.json'}:
        data = (SITE / path).read_bytes()
        if listed[path]['sha256'] != sha256(data) or listed[path]['bytes'] != len(data):
            raise ValueError(f'site.json checksum mismatch: {path}')
    DIST.mkdir(exist_ok=True)
    archive = DIST / f'feros-sources-{tag}.tar.gz'
    checksum = DIST / 'SHA256SUMS'
    if archive.exists() or checksum.exists():
        raise ValueError('Release output exists; clean dist before packaging')
    # gzip mtime=0 and sorted, normalized tar metadata for reproducible artifacts.
    import gzip
    with archive.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as tar:
                for rel in sorted(expected):
                    data = (SITE / rel).read_bytes()
                    info = tarfile.TarInfo(rel)
                    info.size = len(data)
                    info.mode = 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mtime = 0
                    tar.addfile(info, io.BytesIO(data))
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        if {m.name for m in members} != expected or any(not m.isfile() for m in members):
            raise ValueError('Archive inventory mismatch')
        for member in members:
            if sha256(tar.extractfile(member).read()) != sha256((SITE / member.name).read_bytes()):
                raise ValueError(f'Archive content mismatch: {member.name}')
    checksum.write_text(f'{sha256(archive.read_bytes())}  {archive.name}\n', encoding='utf-8', newline='\n')
    print(f'Created and verified {archive.name} and SHA256SUMS for {commit}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    try:
        package(args.tag)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, f'Packaging failed: {error}\n')
