"""Verify complete OCI archives and publish their unchanged multi-platform index.

Keep identical in platform and releases repositories. No archive is extracted.
"""
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

INDEX = 'application/vnd.oci.image.index.v1+json'
INDEX_TYPES = {INDEX, 'application/vnd.docker.distribution.manifest.list.v2+json'}
MANIFEST_TYPES = {'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'}
CONFIG_TYPES = {'application/vnd.oci.image.config.v1+json', 'application/vnd.docker.container.image.v1+json'}
EMPTY_CONFIG = 'application/vnd.oci.empty.v1+json'
ATTESTATION = 'application/vnd.docker.attestation.manifest.v1+json'
LAYER_TYPES = {'application/vnd.oci.image.layer.v1.tar', 'application/vnd.oci.image.layer.v1.tar+gzip',
               'application/vnd.oci.image.layer.v1.tar+zstd', 'application/vnd.docker.image.rootfs.diff.tar.gzip'}
SHA256 = re.compile(r'sha256:[0-9a-f]{64}')
MAX_JSON = 16 * 1024 * 1024
MAX_METADATA = 128 * 1024 * 1024
MAX_MEMBERS = 4096
VERSION_TAG = re.compile(r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?')


def _digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate OCI JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Invalid OCI JSON constant: ' + value)


class _Archive:
    def __init__(self, archive):
        self.archive = archive
        self.files = {}
        self.documents = {}
        self.metadata_size = 0
        seen = set()
        for member in archive:
            name = member.name
            while name.startswith('./'):
                name = name[2:]
            name = name.rstrip('/')
            if (name.startswith('/') or '\\' in name or '..' in name.split('/') or
                    any(part == '' for part in name.split('/'))):
                raise ValueError('Unsafe OCI archive member path')
            if name in seen or len(seen) >= MAX_MEMBERS:
                raise ValueError('Duplicate or too many OCI archive members')
            seen.add(name)
            if member.isdir() and name in {'.', 'blobs', 'blobs/sha256'}:
                continue
            if not member.isfile() or member.issparse():
                raise ValueError('OCI archive members must be regular files or layout directories')
            if name not in {'oci-layout', 'index.json'} and not re.fullmatch(r'blobs/sha256/[0-9a-f]{64}', name):
                raise ValueError('Unexpected OCI archive file path')
            self.files[name] = member
            if name.startswith('blobs/'):
                digest = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                if digest.hexdigest() != name.rsplit('/', 1)[1]:
                    raise ValueError('OCI blob digest mismatch: ' + name)

    def document(self, name):
        if name in self.documents:
            return self.documents[name]
        if name not in self.files:
            raise ValueError('Missing OCI metadata file: ' + name)
        member = self.files[name]
        if member.size > MAX_JSON or self.metadata_size + member.size > MAX_METADATA:
            raise ValueError('OCI JSON metadata is too large')
        self.metadata_size += member.size
        try:
            with self.archive.extractfile(member) as stream:
                document = json.loads(stream.read(MAX_JSON + 1), object_pairs_hook=_unique_keys,
                                      parse_constant=_invalid_constant)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise ValueError('Invalid OCI JSON metadata') from error
        if not isinstance(document, dict):
            raise ValueError('OCI JSON metadata must be an object')
        self.documents[name] = document
        return document

    def blob(self, descriptor, media_types):
        if (not isinstance(descriptor, dict) or not isinstance(descriptor.get('mediaType'), str) or
                descriptor['mediaType'] not in media_types or
                not isinstance(descriptor.get('digest'), str) or not SHA256.fullmatch(descriptor['digest']) or
                type(descriptor.get('size')) is not int or descriptor['size'] < 0):
            raise ValueError('Invalid OCI descriptor digest, size or media type')
        if descriptor.get('urls'):
            raise ValueError('External OCI blob URLs are forbidden')
        name = 'blobs/sha256/' + descriptor['digest'][7:]
        if name not in self.files:
            raise ValueError('Missing OCI descriptor blob: ' + descriptor['digest'])
        if self.files[name].size != descriptor['size']:
            raise ValueError('OCI descriptor size mismatch: ' + descriptor['digest'])
        if 'data' in descriptor:
            try:
                if not isinstance(descriptor['data'], str) or len(descriptor['data']) > MAX_JSON * 2:
                    raise ValueError('Invalid inline OCI descriptor data')
                data = base64.b64decode(descriptor['data'], validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError('Invalid inline OCI descriptor data') from error
            if len(data) != descriptor['size'] or _digest(data) != descriptor['digest']:
                raise ValueError('Inline OCI descriptor digest or size mismatch')
        return name

    def manifest(self, descriptor):
        manifest = self.document(self.blob(descriptor, MANIFEST_TYPES))
        if (type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 2 or
                manifest.get('mediaType') != descriptor['mediaType'] or not isinstance(manifest.get('layers'), list)):
            raise ValueError('Invalid OCI image manifest')
        return manifest

    def runnable(self, descriptor):
        platform = descriptor.get('platform', {})
        architecture = platform.get('architecture') if isinstance(platform, dict) else None
        if (not isinstance(platform, dict) or platform.get('os') != 'linux' or architecture not in ('amd64', 'arm64') or
                platform.get('variant') not in ((None, '') if architecture == 'amd64' else (None, '', 'v8'))):
            raise ValueError('OCI runnable platform must be linux/amd64 or linux/arm64')
        manifest = self.manifest(descriptor)
        if 'artifactType' in manifest or 'subject' in manifest:
            raise ValueError('OCI runnable platform cannot be an artifact')
        config = self.document(self.blob(manifest.get('config'), CONFIG_TYPES))
        if (config.get('os') != 'linux' or config.get('architecture') != architecture or
                config.get('variant') not in ((None, '') if architecture == 'amd64' else (None, '', 'v8')) or
                not isinstance(config.get('config'), dict)):
            raise ValueError('OCI image config must match its declared platform')
        rootfs = config.get('rootfs', {})
        diff_ids = rootfs.get('diff_ids') if isinstance(rootfs, dict) else None
        if (not isinstance(rootfs, dict) or rootfs.get('type') != 'layers' or not isinstance(diff_ids, list) or
                len(diff_ids) != len(manifest['layers']) or not manifest['layers'] or
                any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in diff_ids)):
            raise ValueError('Invalid OCI image config root filesystem')
        for layer in manifest['layers']:
            self.blob(layer, LAYER_TYPES)
        return architecture

    def attestation(self, descriptor, images):
        annotations = descriptor.get('annotations', {})
        target = annotations.get('vnd.docker.reference.digest') if isinstance(annotations, dict) else None
        if (not isinstance(annotations, dict) or annotations.get('vnd.docker.reference.type') != 'attestation-manifest' or
                not isinstance(target, str) or target not in images or
                descriptor.get('platform') != {'architecture': 'unknown', 'os': 'unknown'}):
            raise ValueError('Unknown OCI platform must be a bound BuildKit attestation')
        manifest = self.manifest(descriptor)
        config_descriptor = manifest.get('config')
        config = self.document(self.blob(config_descriptor, CONFIG_TYPES | {EMPTY_CONFIG}))
        if manifest.get('artifactType') == ATTESTATION:
            if config_descriptor['mediaType'] != EMPTY_CONFIG or config != {} or manifest.get('subject') != {
                    key: images[target][key] for key in ('mediaType', 'digest', 'size')}:
                raise ValueError('Invalid OCI artifact attestation config or subject')
        elif ('artifactType' in manifest or 'subject' in manifest or config_descriptor['mediaType'] not in CONFIG_TYPES or
              config.get('architecture') != 'unknown' or config.get('os') != 'unknown'):
            raise ValueError('Invalid BuildKit attestation config')
        if not manifest['layers']:
            raise ValueError('BuildKit attestation has no statements')
        for layer in manifest['layers']:
            if not isinstance(layer, dict) or layer.get('mediaType') != 'application/vnd.in-toto+json':
                raise ValueError('BuildKit attestation layers must be in-toto statements')
            statement = self.document(self.blob(layer, {'application/vnd.in-toto+json'}))
            subjects = statement.get('subject', [])
            predicate = statement.get('predicateType')
            layer_annotations = layer.get('annotations', {})
            if (statement.get('_type') not in ('https://in-toto.io/Statement/v0.1', 'https://in-toto.io/Statement/v1') or
                    not isinstance(subjects, list) or not isinstance(predicate, str) or not predicate or
                    not isinstance(statement.get('predicate'), dict) or
                    not any(isinstance(subject, dict) and isinstance(subject.get('digest'), dict) and
                            subject['digest'].get('sha256') == target[7:] for subject in subjects) or
                    not isinstance(layer_annotations, dict) or
                    layer_annotations.get('in-toto.io/predicate-type', predicate) != predicate):
                raise ValueError('Invalid or unbound BuildKit attestation statement')


def verify_oci_archive(path, expected_digest=None):
    """Return the original root index digest after validating the complete graph."""
    if expected_digest is not None and (not isinstance(expected_digest, str) or not SHA256.fullmatch(expected_digest)):
        raise ValueError('Invalid expected OCI image digest')
    try:
        with tarfile.open(path, mode='r:') as archive:
            contents = _Archive(archive)
            if contents.document('oci-layout') != {'imageLayoutVersion': '1.0.0'}:
                raise ValueError('Unsupported OCI archive layout version')
            root = contents.document('index.json')
            root_name = 'index.json'
            if (type(root.get('schemaVersion')) is not int or root['schemaVersion'] != 2 or
                    root.get('mediaType') != INDEX or not isinstance(root.get('manifests'), list)):
                raise ValueError('Invalid OCI layout wrapper index')
            manifests = root.get('manifests', [])
            if (len(manifests) == 1 and isinstance(manifests[0], dict) and
                    isinstance(manifests[0].get('mediaType'), str) and manifests[0]['mediaType'] in INDEX_TYPES):
                root_name = contents.blob(manifests[0], INDEX_TYPES)
                root = contents.document(root_name)
            if (type(root.get('schemaVersion')) is not int or root['schemaVersion'] != 2 or
                    not isinstance(root.get('mediaType'), str) or root['mediaType'] not in INDEX_TYPES or
                    not isinstance(root.get('manifests'), list) or
                    'artifactType' in root or 'subject' in root):
                raise ValueError('Invalid OCI root image index')
            images, attestations, platforms = {}, [], set()
            for descriptor in root['manifests']:
                if not isinstance(descriptor, dict):
                    raise ValueError('Invalid OCI image index descriptor')
                platform = descriptor.get('platform')
                if isinstance(platform, dict) and platform.get('os') == 'unknown':
                    attestations.append(descriptor)
                    continue
                architecture = contents.runnable(descriptor)
                if architecture in platforms or descriptor['digest'] in images:
                    raise ValueError('Duplicate OCI runnable platform')
                platforms.add(architecture)
                images[descriptor['digest']] = descriptor
            if platforms != {'amd64', 'arm64'}:
                raise ValueError('OCI image must contain exactly linux/amd64 and linux/arm64 platforms')
            for descriptor in attestations:
                contents.attestation(descriptor, images)
            with archive.extractfile(contents.files[root_name]) as stream:
                digest = _digest(stream.read(MAX_JSON + 1))
            if expected_digest is not None and expected_digest != digest:
                raise ValueError('OCI archive image digest differs from the scanned source image')
            return digest
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ValueError('Invalid or unreadable OCI archive') from error


def publish_container(directory, tag, *, run=None):
    """Copy a verified index to its version tag, then verify anonymous GHCR access."""
    if not isinstance(tag, str) or not VERSION_TAG.fullmatch(tag):
        raise ValueError('Invalid container release version tag')
    path = Path(directory) / f'craftedsignal_{tag[1:]}_linux_multiarch.oci.tar'
    expected = verify_oci_archive(path)
    destination = 'docker://ghcr.io/craftedsignal/releases:' + tag[1:]
    authfile = str(Path(os.environ.get('DOCKER_CONFIG', Path.home() / '.docker')) / 'config.json')
    run = subprocess.run if run is None else run

    def command(arguments, timeout=120):
        try:
            return run(['skopeo'] + arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError('Container registry operation failed or timed out') from error

    current = command(['inspect', '--raw', '--authfile', authfile, destination])
    if current.returncode == 0:
        if _digest(current.stdout) != expected:
            raise ValueError('Refusing to overwrite an existing container version tag with a different digest')
    elif re.search(rb'\b(?:manifest unknown|name unknown)\b', current.stderr.lower()):
        result = command(['copy', '--all', '--preserve-digests', '--authfile', authfile,
                          'oci-archive:' + str(path), destination], timeout=1800)
        if result.returncode != 0:
            raise ValueError('Failed to publish the approved OCI image: ' + result.stderr.decode(errors='replace')[-2000:])
    else:
        raise ValueError('Cannot inspect existing container version tag: ' + current.stderr.decode(errors='replace')[-2000:])
    copied = command(['inspect', '--raw', '--authfile', authfile, destination])
    if copied.returncode != 0 or _digest(copied.stdout) != expected:
        raise ValueError('Published container root index digest does not match the approved OCI image')
    anonymous = command(['inspect', '--raw', '--no-creds', destination])
    if anonymous.returncode != 0:
        raise ValueError('Container is not anonymously accessible. Make the ghcr.io/craftedsignal/releases package public, then retry approval.')
    if _digest(anonymous.stdout) != expected:
        raise ValueError('Anonymous container root index digest does not match the approved OCI image')
    return expected
