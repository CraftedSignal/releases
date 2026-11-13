import copy
from pathlib import Path
import tempfile
import unittest

from release_assets_test import TAG, SHA, fixture, load


from release_test_support import FakeGitHub

def approved_manifest(release):
    assets = load('release_assets')
    return {'schema': 1, 'source_repository': 'CraftedSignal/platform', 'source_release_id': 10,
            'source_sha': SHA, 'release_id': release['id'], 'tag': release['tag_name'],
            'title': release['name'], 'body_sha256': assets.body_digest(release['body']),
            'prerelease': release['prerelease'], 'target_commitish': release['target_commitish'],
            'assets': assets.asset_records(release)}


class PublishReleaseTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitHub()
        self.api.release.update(draft=True, published_at=None)

    def publish(self, manifest=None, publish=True):
        module = load('publish_release')
        if manifest is None:
            manifest = approved_manifest(self.api.release)
        with tempfile.TemporaryDirectory() as directory:
            return module.publish(self.api, manifest, Path(directory), publish=publish)

    def test_approved_exact_draft_is_published_without_changing_notes_or_assets(self):
        result = self.publish()
        self.assertEqual('published', result)
        self.assertEqual([('PATCH', '/releases/10', {'draft': False, 'make_latest': 'legacy'})], self.api.mutations())
        self.assertEqual(9, sum(c[0] == 'DOWNLOAD' for c in self.api.calls))

    def test_preapproval_review_needs_no_draft_or_asset_access(self):
        module = load('publish_release')
        result = module.review(self.api, approved_manifest(self.api.release))
        self.assertEqual('ready for approval', result)
        self.assertEqual([('GET', '/environments/public-release')], self.api.calls)

    def test_last_api_read_before_publish_is_the_draft_identity(self):
        self.publish()
        index = next(i for i, call in enumerate(self.api.calls) if call[0] == 'PATCH')
        self.assertEqual(('GET', '/releases/10'), self.api.calls[index - 1])

    def test_review_mode_performs_validation_without_writing(self):
        self.assertEqual('ready', self.publish(publish=False))
        self.assertEqual([], self.api.mutations())

    def test_mutated_notes_identity_asset_id_or_bytes_never_publish(self):
        for change in ('body', 'name', 'tag_name', 'prerelease', 'target_commitish', 'id', 'asset_id', 'asset_bytes'):
            with self.subTest(change=change):
                self.setUp()
                manifest = approved_manifest(self.api.release)
                if change == 'asset_id':
                    self.api.release['assets'][0]['id'] += 1000
                elif change == 'asset_bytes':
                    self.api.files[self.api.release['assets'][0]['name']] = b'tampered'
                else:
                    self.api.release[change] = {'id': 11, 'prerelease': True}.get(change, 'changed')
                with self.assertRaises(ValueError):
                    self.publish(manifest)
                self.assertEqual([], self.api.mutations())

    def test_unprotected_or_wrong_reviewer_environment_fails_closed(self):
        for change in ('missing_rules', 'admin_bypass', 'wrong_reviewer', 'extra_reviewer'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'missing_rules':
                    self.api.environment['protection_rules'] = []
                elif change == 'admin_bypass':
                    self.api.environment['can_admins_bypass'] = True
                elif change == 'wrong_reviewer':
                    self.api.environment['protection_rules'][0]['reviewers'][0]['reviewer']['id'] = 1
                else:
                    self.api.environment['protection_rules'][0]['reviewers'].append({'type': 'User', 'reviewer': {'id': 1}})
                with self.assertRaisesRegex(ValueError, 'environment|reviewer'):
                    self.publish()
                self.assertEqual([], self.api.mutations())

    def test_revalidation_detects_draft_changes_during_download(self):
        manifest = approved_manifest(self.api.release)
        def mutate(api):
            if api.release_reads == 2:
                api.release['body'] += 'late edit'
        self.api.mutate_on_read = mutate
        with self.assertRaisesRegex(ValueError, 'manifest|changed'):
            self.publish(manifest)
        self.assertEqual([], self.api.mutations())

    def test_gate_weakened_during_validation_prevents_the_publish_write(self):
        get = self.api.get
        gate_reads = 0
        def change_gate(path):
            nonlocal gate_reads
            if path == '/environments/public-release':
                gate_reads += 1
                if gate_reads == 2:
                    self.api.environment['protection_rules'] = []
            return get(path)
        self.api.get = change_gate
        with self.assertRaisesRegex(ValueError, 'environment'):
            self.publish()
        self.assertEqual([], self.api.mutations())

    def test_concurrent_publication_during_validation_is_detected(self):
        manifest = approved_manifest(self.api.release)
        def mutate(api):
            if api.release_reads == 2:
                api.release.update(draft=False, published_at='2026-11-13T01:00:00Z')
        self.api.mutate_on_read = mutate
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.publish(manifest)
        self.assertEqual([], self.api.mutations())

    def test_partial_draft_is_rejected_before_any_download_or_publish(self):
        manifest = approved_manifest(self.api.release)
        self.api.release['assets'].pop()
        with self.assertRaisesRegex(ValueError, 'asset'):
            self.publish(manifest)
        self.assertEqual([], self.api.mutations())
        self.assertFalse(any(c[0] == 'DOWNLOAD' for c in self.api.calls))

    def test_duplicate_run_after_matching_publication_does_not_write_again(self):
        manifest = approved_manifest(self.api.release)
        self.publish(manifest)
        self.api.calls.clear()
        self.assertEqual('already published', self.publish(manifest))
        self.assertEqual([], self.api.mutations())

    def test_malformed_manifest_fails_before_any_api_calls(self):
        for manifest in ({}, {'schema': 2}, dict(approved_manifest(self.api.release), release_id=True),
                         dict(approved_manifest(self.api.release), source_repository='someone/else'),
                         dict(approved_manifest(self.api.release), source_sha='main')):
            with self.subTest(manifest=manifest):
                self.api.calls.clear()
                with self.assertRaises(ValueError):
                    self.publish(manifest)
                self.assertEqual([], self.api.calls)

    def test_stable_approval_does_not_force_an_older_release_to_latest(self):
        # Approval runs are independent per tag and can complete out of order.
        # GitHub's legacy mode selects latest using date and semantic version.
        self.publish()
        self.assertEqual('legacy', self.api.mutations()[0][2]['make_latest'])

    def test_prerelease_remains_prerelease_and_never_becomes_latest(self):
        self.api.release['prerelease'] = True
        self.publish()
        self.assertEqual('false', self.api.mutations()[0][2]['make_latest'])


if __name__ == '__main__':
    unittest.main()
