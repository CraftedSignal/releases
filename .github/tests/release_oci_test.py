import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from release_assets_test import load
from oci_test_support import RegistryBoundary, archive_files, json_bytes, oci_fixture, tar_bytes


def root_files(files):
    wrapper = json.loads(files['index.json'])
    descriptor = wrapper['manifests'][0]
    name = 'blobs/sha256/' + descriptor['digest'][7:]
    return name, json.loads(files[name])


def replace_blob(files, name, value):
    """Rewrite a fixture blob and all parent digest/size descriptors."""
    data = json_bytes(value)
    old = name.removeprefix('blobs/sha256/')
    new = hashlib.sha256(data).hexdigest()
    del files[name]
    files['blobs/sha256/' + new] = data
    for parent, contents in list(files.items()):
        if parent == 'oci-layout' or parent == 'blobs/sha256/' + new:
            continue
        try:
            document = json.loads(contents)
        except (UnicodeError, ValueError):
            continue
        changed = False
        def visit(node):
            nonlocal changed
            if isinstance(node, dict):
                if node.get('digest') == 'sha256:' + old:
                    node.update(digest='sha256:' + new, size=len(data))
                    changed = True
                for child in node.values():
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        visit(document)
        if changed:
            if parent == 'index.json':
                files[parent] = json_bytes(document)
            else:
                replace_blob(files, parent, document)


class OCIArchiveTest(unittest.TestCase):
    def verify(self, data, expected_digest=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.oci.tar'
            path.write_bytes(data)
            return load('release_oci').verify_oci_archive(path, expected_digest)

    def test_complete_wrapped_or_direct_indexes_return_original_image_digest(self):
        for wrapped in (True, False):
            with self.subTest(wrapped=wrapped):
                data, digest = oci_fixture(wrapped=wrapped)
                self.assertEqual(digest, self.verify(data, digest))

    def test_source_registry_index_digest_must_match_the_archived_image(self):
        data, _ = oci_fixture()
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.verify(data, 'sha256:' + '0' * 64)

    def test_platform_set_requires_exactly_one_amd64_and_one_arm64_image(self):
        for platforms in (('amd64',), ('arm64',), ('amd64', 'arm64', 's390x'), ('amd64', 'arm64', 'amd64')):
            with self.subTest(platforms=platforms):
                data, _ = oci_fixture(platforms=platforms)
                with self.assertRaisesRegex(ValueError, 'platform|duplicate'):
                    self.verify(data)

    def test_descriptor_platform_must_match_actual_image_config(self):
        data, _ = oci_fixture(config_platforms={'arm64': 'amd64'})
        with self.assertRaisesRegex(ValueError, 'config|platform'):
            self.verify(data)

    def test_corrupted_or_missing_layer_and_incorrect_descriptor_size_are_rejected(self):
        original, _ = oci_fixture()
        for change in ('bytes', 'missing', 'size'):
            with self.subTest(change=change):
                files = archive_files(original)
                name, root = root_files(files)
                manifest_name = 'blobs/sha256/' + root['manifests'][0]['digest'][7:]
                manifest = json.loads(files[manifest_name])
                layer_name = 'blobs/sha256/' + manifest['layers'][0]['digest'][7:]
                if change == 'bytes':
                    files[layer_name] += b'changed'
                elif change == 'missing':
                    del files[layer_name]
                else:
                    manifest['layers'][0]['size'] += 1
                    replace_blob(files, manifest_name, manifest)
                with self.assertRaisesRegex(ValueError, 'digest|[Mm]issing|size'):
                    self.verify(tar_bytes(files))

    def test_path_traversal_links_duplicates_and_special_tar_members_are_rejected(self):
        original, _ = oci_fixture()
        for name, kind in (('../outside', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('blobs/sha256/link', tarfile.SYMTYPE), ('hardlink', tarfile.LNKTYPE),
                           ('pipe', tarfile.FIFOTYPE), ('index.json', tarfile.REGTYPE)):
            with self.subTest(name=name, kind=kind):
                output = io.BytesIO()
                with tarfile.open(fileobj=output, mode='w') as archive:
                    for path, data in archive_files(original).items():
                        member = tarfile.TarInfo(path)
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = 'index.json' if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ''
                    archive.addfile(member, io.BytesIO())
                with self.assertRaisesRegex(ValueError, 'path|member|duplicate|file'):
                    self.verify(output.getvalue())

    def test_oversized_json_metadata_is_rejected_before_loading(self):
        data, _ = oci_fixture()
        files = archive_files(data)
        files['index.json'] = b' ' * (16 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, 'metadata|large'):
            self.verify(tar_bytes(files))

    def test_duplicate_json_keys_are_rejected(self):
        data, _ = oci_fixture()
        files = archive_files(data)
        files['oci-layout'] = b'{"imageLayoutVersion":"1.0.0","imageLayoutVersion":"0.0.0"}'
        with self.assertRaisesRegex(ValueError, 'duplicate|JSON'):
            self.verify(tar_bytes(files))

    def test_valid_buildkit_attestations_are_preserved_and_verified(self):
        for attestations in (True, 'artifact'):
            with self.subTest(attestations=attestations):
                data, digest = oci_fixture(attestations=attestations)
                self.assertEqual(digest, self.verify(data))

    def test_layout_wrapper_must_itself_be_a_valid_oci_index(self):
        original, _ = oci_fixture()
        for value in ({'schemaVersion': 1}, {'mediaType': 'unsupported'}):
            with self.subTest(value=value):
                files = archive_files(original)
                wrapper = json.loads(files['index.json'])
                wrapper.update(value)
                files['index.json'] = json_bytes(wrapper)
                with self.assertRaisesRegex(ValueError, 'index|wrapper'):
                    self.verify(tar_bytes(files))

    def test_unknown_platform_must_be_a_bound_attestation_with_no_runnable_layers(self):
        original, _ = oci_fixture(attestations=True)
        for change in ('unmarked', 'unbound', 'runnable_layer', 'unbound_statement'):
            with self.subTest(change=change):
                files = archive_files(original)
                root_name, root = root_files(files)
                attestation = root['manifests'][2]
                if change == 'unmarked':
                    attestation.pop('annotations')
                    replace_blob(files, root_name, root)
                elif change == 'unbound':
                    attestation['annotations']['vnd.docker.reference.digest'] = 'sha256:' + '0' * 64
                    replace_blob(files, root_name, root)
                else:
                    name = 'blobs/sha256/' + attestation['digest'][7:]
                    manifest = json.loads(files[name])
                    if change == 'runnable_layer':
                        manifest['layers'][0]['mediaType'] = 'application/vnd.oci.image.layer.v1.tar'
                        replace_blob(files, name, manifest)
                    else:
                        layer = 'blobs/sha256/' + manifest['layers'][0]['digest'][7:]
                        statement = json.loads(files[layer])
                        statement['subject'][0]['digest']['sha256'] = '0' * 64
                        replace_blob(files, layer, statement)
                with self.assertRaisesRegex(ValueError, 'attestation|platform'):
                    self.verify(tar_bytes(files))

    def test_external_blob_urls_cannot_trigger_registry_fetches(self):
        data, _ = oci_fixture()
        files = archive_files(data)
        _, root = root_files(files)
        name = 'blobs/sha256/' + root['manifests'][0]['digest'][7:]
        manifest = json.loads(files[name])
        manifest['layers'][0]['urls'] = ['https://unapproved.invalid/layer']
        replace_blob(files, name, manifest)
        with self.assertRaisesRegex(ValueError, 'external|URL'):
            self.verify(tar_bytes(files))

    def test_malformed_descriptor_field_types_fail_as_validation_errors(self):
        original, _ = oci_fixture()
        for field, value in (('mediaType', []), ('digest', {}), ('size', True),
                             ('platform', {'architecture': [], 'os': 'linux'})):
            with self.subTest(field=field):
                files = archive_files(original)
                name, root = root_files(files)
                root['manifests'][0][field] = value
                replace_blob(files, name, root)
                with self.assertRaises(ValueError):
                    self.verify(tar_bytes(files))


class ContainerPublicationTest(unittest.TestCase):
    def publish(self, boundary, data=None):
        data = oci_fixture()[0] if data is None else data
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'craftedsignal_1.2.3_linux_multiarch.oci.tar'
            path.write_bytes(data)
            return load('release_oci').publish_container(Path(directory), 'v1.2.3', run=boundary)

    def test_publication_copies_original_multiarch_digest_and_supports_idempotent_retry(self):
        registry = RegistryBoundary()
        digest = oci_fixture()[1]
        self.assertEqual(digest, self.publish(registry))
        self.assertEqual(digest, 'sha256:' + hashlib.sha256(registry.content).hexdigest())
        self.assertEqual(digest, self.publish(registry))
        self.assertEqual(1, registry.copies)
        self.assertEqual({'docker://ghcr.io/craftedsignal/releases:1.2.3'}, registry.references)

    def test_existing_mismatched_version_tag_is_never_overwritten(self):
        registry = RegistryBoundary(existing=b'another approved index')
        with self.assertRaisesRegex(ValueError, 'existing|overwrite|different'):
            self.publish(registry)
        self.assertEqual(b'another approved index', registry.content)
        self.assertEqual(0, registry.copies)

    def test_network_or_authentication_failure_is_not_treated_as_absent_tag(self):
        for error in (b'connection timed out', b'unauthorized: authentication required'):
            with self.subTest(error=error):
                registry = RegistryBoundary(inspect_error=error)
                with self.assertRaisesRegex(ValueError, 'inspect|registry'):
                    self.publish(registry)
                self.assertIsNone(registry.content)

    def test_copy_digest_mismatch_or_private_package_prevents_success(self):
        for registry in (RegistryBoundary(changed_copy=True), RegistryBoundary(public=False)):
            with self.subTest(private=not registry.public):
                with self.assertRaisesRegex(ValueError, 'digest|anonymous|public'):
                    self.publish(registry)

    def test_invalid_archive_prevents_every_registry_operation(self):
        registry = RegistryBoundary()
        with self.assertRaisesRegex(ValueError, 'OCI|archive|tar'):
            self.publish(registry, b'invalid tar')
        self.assertIsNone(registry.content)
        self.assertEqual(0, registry.copies)


if __name__ == '__main__':
    unittest.main()
