#!/usr/bin/env python3
"""Verify an immutable dispatch manifest; only the environment-gated job uses --publish."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from github_release_api import GitHub
from release_assets import SHA, SHA256, asset_records, expected_names, positive_id, snapshot, verify_files

KEYS = {'schema', 'source_repository', 'source_release_id', 'source_sha', 'release_id', 'tag',
        'title', 'body_sha256', 'prerelease', 'target_commitish', 'assets'}


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != KEYS or type(manifest['schema']) is not int or manifest['schema'] != 1:
        raise ValueError('Invalid approval manifest schema')
    if manifest['source_repository'] != 'CraftedSignal/platform':
        raise ValueError('Invalid approval manifest source repository')
    positive_id(manifest['source_release_id'])
    positive_id(manifest['release_id'])
    for key, pattern in (('source_sha', SHA), ('target_commitish', SHA), ('body_sha256', SHA256)):
        if not isinstance(manifest[key], str) or not pattern.fullmatch(manifest[key]):
            raise ValueError('Invalid approval manifest ' + key)
    if type(manifest['prerelease']) is not bool or not isinstance(manifest['title'], str) or not manifest['title'].strip():
        raise ValueError('Invalid approval manifest release metadata')
    expected_names(manifest['tag'])
    if not isinstance(manifest['assets'], list) or not all(isinstance(a, dict) for a in manifest['assets']):
        raise ValueError('Invalid approval manifest assets')
    records = asset_records({'tag_name': manifest['tag'], 'assets': [dict(a, state='uploaded') for a in manifest['assets']]})
    if records != manifest['assets']:
        raise ValueError('Invalid approval manifest asset records')


def verify_gate(api):
    environment = api.get('/environments/public-release')
    rules = [r for r in environment.get('protection_rules', []) if r.get('type') == 'required_reviewers']
    if environment.get('name') != 'public-release' or environment.get('can_admins_bypass') is not False or len(rules) != 1:
        raise ValueError('Public release environment must require human approval without admin bypass')
    reviewers = rules[0].get('reviewers', [])
    if len(reviewers) != 1 or reviewers[0].get('type') != 'User' or reviewers[0].get('reviewer', {}).get('id') != 5222512:
        raise ValueError('Public release environment must require sole reviewer hazcod')


def verify_identity(release, manifest):
    current = snapshot(release)
    if any(current[key] != manifest[key] for key in ('release_id', 'tag', 'title', 'body_sha256', 'prerelease', 'target_commitish', 'assets')):
        raise ValueError('Release changed from the approval manifest; prepare a new approval run')
    if release['draft'] == bool(release.get('published_at')):
        raise ValueError('Invalid release publication state')
    return current


def review(api, manifest):
    # Read-only tokens cannot reliably access drafts. Private preparation has
    # already verified the bytes; the approved write-token job verifies again.
    validate_manifest(manifest)
    verify_gate(api)
    return 'ready for approval'


def publish(api, manifest, directory, publish=False):
    validate_manifest(manifest)
    verify_gate(api)
    path = f'/releases/{manifest["release_id"]}'
    release = api.get(path)
    before = verify_identity(release, manifest)
    for asset in manifest['assets']:
        api.download(asset['id'], Path(directory) / asset['name'])
    verify_files(release, directory)
    if publish and release['draft']:
        # Check the gate before the final draft GET, minimizing the non-atomic
        # GET/PATCH interval. GitHub offers no documented atomic draft finalize.
        verify_gate(api)
    after = api.get(path)
    if verify_identity(after, manifest) != before:
        raise ValueError('Release changed during validation')
    if not release['draft']:
        return 'already published'
    if not publish:
        return 'ready'
    result = api.patch(path, {'draft': False, 'make_latest': 'false' if manifest['prerelease'] else 'legacy'})
    verify_identity(result, manifest)
    if result['draft']:
        raise ValueError('GitHub did not publish the approved draft')
    return 'published'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if (os.environ.get('GITHUB_REPOSITORY') != 'CraftedSignal/releases' or
            os.environ.get('GITHUB_REF') != 'refs/heads/main' or
            os.environ.get('GITHUB_EVENT_NAME') != 'repository_dispatch'):
        raise ValueError('Only trusted main-branch release dispatches are accepted')
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    if event.get('action') != 'platform-release-ready' or event.get('repository', {}).get('full_name') != 'CraftedSignal/releases':
        raise ValueError('Invalid release dispatch event')
    manifest = event.get('client_payload', {}).get('manifest')
    api = GitHub('CraftedSignal/releases', os.environ['GH_TOKEN'])
    if args.publish:
        with tempfile.TemporaryDirectory() as directory:
            result = publish(api, manifest, Path(directory), publish=True)
    else:
        result = review(api, manifest)
    summary = f'Release {manifest["tag"]}: {result}. Draft/release ID: {manifest["release_id"]}.\n'
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as stream:
            stream.write('### Public release review\n\n' + summary + '\n')
            stream.write(f'[Review the release](https://github.com/CraftedSignal/releases/releases)\n\n')
            stream.write('The approval binds the release title, notes SHA256, prerelease flag and every asset ID, size and SHA256.\n\n')
            stream.write('```json\n' + json.dumps(manifest, indent=2, sort_keys=True) + '\n```\n')


if __name__ == '__main__':
    main()
