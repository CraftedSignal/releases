"""Small, real OCI image archives for release contract and publication tests."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

INDEX = 'application/vnd.oci.image.index.v1+json'
MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
CONFIG = 'application/vnd.oci.image.config.v1+json'
LAYER = 'application/vnd.oci.image.layer.v1.tar+gzip'


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def tar_bytes(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name == 'craftedsignal' else 0o644
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def archive_files(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        return {member.name: archive.extractfile(member).read() for member in archive if member.isfile()}


def oci_fixture(platforms=('amd64', 'arm64'), config_platforms=None, attestations=False, wrapped=True):
    """Return (archive bytes, root index digest), including complete runnable blobs."""
    files = {'oci-layout': b'{"imageLayoutVersion":"1.0.0"}'}

    def blob(content, media_type, **extra):
        digest = 'sha256:' + hashlib.sha256(content).hexdigest()
        files['blobs/sha256/' + digest[7:]] = content
        return dict(mediaType=media_type, digest=digest, size=len(content), **extra)

    layer_tar = tar_bytes({'craftedsignal': b'#!/bin/sh\necho CraftedSignal\n'})
    layer = blob(gzip.compress(layer_tar, mtime=0), LAYER)
    images = []
    for architecture in platforms:
        config_arch = (config_platforms or {}).get(architecture, architecture)
        config = blob(json_bytes({'architecture': config_arch, 'os': 'linux',
                                  'config': {'Entrypoint': ['/craftedsignal']},
                                  'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + hashlib.sha256(layer_tar).hexdigest()]},
                                  'history': [{'created_by': 'release test fixture'}]}), CONFIG)
        manifest = {'schemaVersion': 2, 'mediaType': MANIFEST, 'config': config, 'layers': [layer]}
        images.append(blob(json_bytes(manifest), MANIFEST, platform={'os': 'linux', 'architecture': architecture}))
    descriptors = list(images)
    if attestations:
        for image in images:
            config = (blob(b'{}', 'application/vnd.oci.empty.v1+json', data='e30=') if attestations == 'artifact' else
                      blob(json_bytes({'architecture': 'unknown', 'os': 'unknown', 'config': {},
                                       'rootfs': {'type': 'layers', 'diff_ids': []}}), CONFIG))
            statement = {'_type': 'https://in-toto.io/Statement/v0.1',
                         'subject': [{'name': '_', 'digest': {'sha256': image['digest'][7:]}}],
                         'predicateType': 'https://slsa.dev/provenance/v0.2', 'predicate': {}}
            layer = blob(json_bytes(statement), 'application/vnd.in-toto+json',
                         annotations={'in-toto.io/predicate-type': statement['predicateType']})
            manifest = {'schemaVersion': 2, 'mediaType': MANIFEST, 'config': config, 'layers': [layer]}
            if attestations == 'artifact':
                manifest.update(artifactType='application/vnd.docker.attestation.manifest.v1+json',
                                subject={key: image[key] for key in ('mediaType', 'digest', 'size')})
            descriptors.append(blob(json_bytes(manifest), MANIFEST,
                                    platform={'os': 'unknown', 'architecture': 'unknown'},
                                    annotations={'vnd.docker.reference.type': 'attestation-manifest',
                                                 'vnd.docker.reference.digest': image['digest']}))
    root = json_bytes({'schemaVersion': 2, 'mediaType': INDEX, 'manifests': descriptors})
    digest = 'sha256:' + hashlib.sha256(root).hexdigest()
    if wrapped:
        descriptor = blob(root, INDEX, annotations={'org.opencontainers.image.ref.name': 'release'})
        files['index.json'] = json_bytes({'schemaVersion': 2, 'mediaType': INDEX, 'manifests': [descriptor]})
    else:
        files['index.json'] = root
    return tar_bytes(files), digest


class RegistryBoundary:
    """An external Skopeo boundary with registry content and visibility semantics."""
    def __init__(self, *, existing=None, public=True, changed_copy=False, inspect_error=None):
        self.content = existing
        self.public = public
        self.changed_copy = changed_copy
        self.inspect_error = inspect_error
        self.copies = 0
        self.references = set()

    def __call__(self, command, **options):
        self.references.add(command[-1])
        if command[:3] == ['skopeo', 'inspect', '--raw']:
            if self.inspect_error:
                return subprocess.CompletedProcess(command, 1, b'', self.inspect_error)
            if '--no-creds' in command and not self.public:
                return subprocess.CompletedProcess(command, 1, b'', b'unauthorized: authentication required')
            if self.content is None:
                return subprocess.CompletedProcess(command, 1, b'', b'manifest unknown')
            return subprocess.CompletedProcess(command, 0, self.content, b'')
        if command[:4] == ['skopeo', 'copy', '--all', '--preserve-digests']:
            self.copies += 1
            data = Path(command[-2].removeprefix('oci-archive:')).read_bytes()
            files = archive_files(data)
            descriptors = json.loads(files['index.json'])['manifests']
            root_name = ('blobs/sha256/' + descriptors[0]['digest'][7:] if len(descriptors) == 1 and
                         descriptors[0]['mediaType'] == INDEX else 'index.json')
            self.content = files[root_name] if not self.changed_copy else b'changed image index'
            return subprocess.CompletedProcess(command, 0, b'', b'')
        raise AssertionError('Unexpected container command: ' + repr(command))
