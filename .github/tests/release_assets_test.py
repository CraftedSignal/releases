"""Behavioral contract shared verbatim with the private preparation repository."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
TAG = 'v1.2.3'
SHA = 'a' * 40


def load(name):
    path = SCRIPTS / (name + '.py')
    assert path.is_file(), f'Missing release implementation: {path.name}'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    names = [f'craftedsignal_1.2.3_{target}.{extension}' for target, extension in (
        ('linux_amd64', 'tar.gz'), ('linux_arm64', 'tar.gz'),
        ('darwin_arm64', 'tar.gz'), ('windows_amd64', 'zip'))]
    files = {name: b'binary archive: ' + name.encode() for name in names}
    files.update({name + '.sbom.json': b'{"spdxVersion":"SPDX-2.3","packages":[]}' for name in names})
    files['checksums.txt'] = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in sorted(files.items())).encode()
    release = {'id': 10, 'tag_name': TAG, 'name': TAG, 'body': '## Changes\n\nA reviewed feature.\n',
               'prerelease': False, 'draft': False, 'published_at': '2026-11-13T00:00:00Z',
               'target_commitish': SHA, 'assets': []}
    for i, (name, data) in enumerate(sorted(files.items()), 100):
        release['assets'].append({'id': i, 'name': name, 'size': len(data), 'state': 'uploaded',
                                  'digest': 'sha256:' + hashlib.sha256(data).hexdigest()})
    return release, files


class ReleaseAssetsTest(unittest.TestCase):
    def setUp(self):
        self.release, self.files = fixture()

    def validate(self):
        module = load('release_assets')
        with tempfile.TemporaryDirectory() as directory:
            for name, data in self.files.items():
                (Path(directory) / name).write_bytes(data)
            return module.verify_files(self.release, Path(directory))

    def test_complete_binary_sbom_and_checksum_set_passes(self):
        self.assertEqual(9, len(self.validate()))

    def test_no_empty_partial_or_extra_asset_set_is_accepted(self):
        for assets in ([], self.release['assets'][:-1], self.release['assets'] + [dict(self.release['assets'][0], name='../extra')]):
            with self.subTest(assets=len(assets)):
                self.release['assets'] = assets
                with self.assertRaisesRegex(ValueError, 'asset|Asset'):
                    self.validate()
            self.release, self.files = fixture()

    def test_duplicate_asset_names_and_ids_are_rejected(self):
        for field in ('id', 'name'):
            with self.subTest(field=field):
                self.release['assets'][1][field] = self.release['assets'][0][field]
                with self.assertRaises(ValueError):
                    self.validate()
            self.release, self.files = fixture()

    def test_missing_malformed_digest_or_unfinished_upload_is_rejected(self):
        for field, value in (('digest', None), ('digest', 'sha256:not-a-hash'), ('state', 'starter'), ('id', True), ('size', 0)):
            with self.subTest(field=field, value=value):
                self.release['assets'][0][field] = value
                with self.assertRaises(ValueError):
                    self.validate()
            self.release, self.files = fixture()

    def test_downloaded_bytes_must_match_github_digest_and_size(self):
        name = self.release['assets'][1]['name']
        self.files[name] = b'changed download'
        with self.assertRaisesRegex(ValueError, 'digest|size'):
            self.validate()

    def test_checksums_must_cover_every_archive_and_sbom_exactly(self):
        original = self.files['checksums.txt']
        for content in (original.splitlines(keepends=True)[0], original + original.splitlines(keepends=True)[0],
                        original + b'a' * 64 + b'  ../outside\n', original.replace(b'  ', b' ', 1)):
            with self.subTest(content=content[:70]):
                self.files['checksums.txt'] = content
                asset = self.release['assets'][0]
                asset['size'] = len(content)
                asset['digest'] = 'sha256:' + hashlib.sha256(content).hexdigest()
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    self.validate()

    def test_checksums_cannot_contradict_github_digests(self):
        self.files['checksums.txt'] = self.files['checksums.txt'].replace(self.files['checksums.txt'][:64], b'0' * 64, 1)
        self.release['assets'][0]['digest'] = 'sha256:' + hashlib.sha256(self.files['checksums.txt']).hexdigest()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.validate()

    def test_tag_must_be_semantic_version_without_shell_or_path_syntax(self):
        for tag in ('1.2.3', 'v01.2.3', 'v1.2.3/../../x', 'v1.2.3\n', 'v1.2.3$(echo x)'):
            with self.subTest(tag=tag):
                self.release['tag_name'] = tag
                with self.assertRaises(ValueError):
                    self.validate()


if __name__ == '__main__':
    unittest.main()
