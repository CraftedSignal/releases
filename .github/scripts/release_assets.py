"""Fail-closed release contract. Keep identical in platform and releases repositories."""
import hashlib
import json
from pathlib import Path
import re

VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
SHA256 = re.compile(r'sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')


def positive_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError('Invalid asset or release ID/size')
    return value


def expected_names(tag):
    if not isinstance(tag, str) or not re.fullmatch('v' + VERSION, tag):
        raise ValueError('Invalid release tag: expected v-prefixed semantic version')
    version = tag[1:]
    archives = {f'craftedsignal_{version}_{target}.{extension}' for target, extension in (
        ('linux_amd64', 'tar.gz'), ('linux_arm64', 'tar.gz'),
        ('darwin_arm64', 'tar.gz'), ('windows_amd64', 'zip'))}
    containers = {f'craftedsignal_{version}_linux_multiarch.oci.tar'} | {
        f'craftedsignal_{version}_linux_{arch}.oci.sbom.json' for arch in ('amd64', 'arm64')}
    return archives | {name + '.sbom.json' for name in archives} | containers | {'checksums.txt'}


def asset_records(release, partial=False):
    expected = expected_names(release.get('tag_name'))
    assets = release.get('assets')
    if not isinstance(assets, list):
        raise ValueError('Missing release assets')
    records, ids = {}, set()
    for asset in assets:
        name = asset.get('name')
        if not isinstance(name, str) or name not in expected or name in records:
            raise ValueError('Unexpected or duplicate release asset name')
        identifier = positive_id(asset.get('id'))
        if identifier in ids:
            raise ValueError('Duplicate release asset ID')
        ids.add(identifier)
        digest = asset.get('digest')
        if not isinstance(digest, str) or not SHA256.fullmatch(digest) or asset.get('state') != 'uploaded':
            raise ValueError('Missing digest or unfinished release asset upload')
        records[name] = {'name': name, 'id': identifier, 'size': positive_id(asset.get('size')), 'digest': digest}
    if not partial and set(records) != expected:
        raise ValueError('Incomplete release asset set: require four binaries, six SBOMs, the multi-platform OCI archive and checksums.txt')
    return [records[name] for name in sorted(records)]


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return 'sha256:' + digest.hexdigest()


def body_digest(body):
    if not isinstance(body, str) or not body.strip():
        raise ValueError('Release notes must not be empty')
    return 'sha256:' + hashlib.sha256(body.encode()).hexdigest()


def verify_files(release, directory):
    records = asset_records(release)
    for record in records:
        path = Path(directory) / record['name']
        if path.stat().st_size != record['size'] or sha256_file(path) != record['digest']:
            raise ValueError('Downloaded asset digest or size mismatch: ' + record['name'])
    checksums = {}
    try:
        lines = (Path(directory) / 'checksums.txt').read_text(encoding='ascii').splitlines()
    except (UnicodeError, OSError) as error:
        raise ValueError('Invalid checksum file') from error
    for line in lines:
        match = re.fullmatch(r'([0-9a-f]{64}) [ *]([^\r\n]+)', line)
        if not match or match[2] in checksums:
            raise ValueError('Malformed or duplicate checksum entry')
        checksums[match[2]] = 'sha256:' + match[1]
    expected = {r['name']: r['digest'] for r in records if r['name'] != 'checksums.txt'}
    if checksums != expected:
        raise ValueError('checksum entries must match every binary and SBOM digest exactly')
    verify_container_files(release['tag_name'], directory)
    return records


def snapshot(release, partial=False):
    positive_id(release.get('id'))
    if type(release.get('draft')) is not bool or type(release.get('prerelease')) is not bool:
        raise ValueError('Invalid release state')
    if not isinstance(release.get('name'), str) or not release['name'].strip():
        raise ValueError('Missing release title')
    return {'release_id': release['id'], 'tag': release['tag_name'], 'title': release['name'],
            'body_sha256': body_digest(release.get('body')), 'prerelease': release['prerelease'],
            'target_commitish': release.get('target_commitish'), 'draft': release['draft'],
            'published_at': release.get('published_at'), 'assets': asset_records(release, partial=partial)}


def verify_container_files(tag, directory, expected_digest=None):
    from release_oci import verify_oci_archive
    expected_names(tag)
    version = tag[1:]
    digest = verify_oci_archive(Path(directory) / f'craftedsignal_{version}_linux_multiarch.oci.tar', expected_digest=expected_digest)
    for arch in ('amd64', 'arm64'):
        path = Path(directory) / f'craftedsignal_{version}_linux_{arch}.oci.sbom.json'
        try:
            sbom = json.loads(path.read_text())
            target = sbom['source']['metadata']
            if (sbom['source']['type'] != 'image' or target['os'] != 'linux' or
                    target['architecture'] != arch or not isinstance(sbom['artifacts'], list)):
                raise ValueError('Container SBOM platform does not match its release filename')
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError('Invalid container SBOM: ' + path.name) from error
    return digest
