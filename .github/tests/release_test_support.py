import copy
from pathlib import Path
from release_assets_test import TAG, SHA, fixture

def gate():
    return {'name': 'public-release', 'can_admins_bypass': False, 'protection_rules': [
        {'type': 'required_reviewers', 'prevent_self_review': False,
         'reviewers': [{'type': 'User', 'reviewer': {'id': 5222512, 'login': 'hazcod'}}]}]}


class FakeGitHub:
    """In-memory API boundary; tests run the real validation and orchestration."""
    def __init__(self, release=None, files=None):
        original, data = fixture()
        self.release = copy.deepcopy(original if release is None else release)
        self.files = copy.deepcopy(data if files is None else files)
        self.environment = gate()
        self.calls = []
        self.mutate_on_read = None
        self.release_reads = 0

    def get(self, path):
        self.calls.append(('GET', path))
        if path == '/environments/public-release':
            return copy.deepcopy(self.environment)
        if path.startswith('/releases?'):
            return [] if self.release is None else [copy.deepcopy(self.release)]
        if path.startswith('/releases/'):
            self.release_reads += 1
            if self.mutate_on_read:
                self.mutate_on_read(self)
            return copy.deepcopy(self.release)
        if path.startswith('/git/ref/'):
            return {'object': {'type': 'commit', 'sha': SHA}}
        raise AssertionError('Unexpected GET: ' + path)

    def post(self, path, data):
        self.calls.append(('POST', path, copy.deepcopy(data)))
        if path == '/releases':
            self.release = dict(copy.deepcopy(data), id=20, assets=[], published_at=None)
            return copy.deepcopy(self.release)
        if path == '/dispatches':
            return None
        raise AssertionError('Unexpected POST: ' + path)

    def patch(self, path, data):
        self.calls.append(('PATCH', path, copy.deepcopy(data)))
        self.release.update(data)
        self.release['published_at'] = '2026-11-13T01:00:00Z'
        return copy.deepcopy(self.release)

    def upload(self, release_id, name, path):
        import hashlib
        data = Path(path).read_bytes()
        self.calls.append(('UPLOAD', release_id, name, data))
        self.files[name] = data
        asset = {'id': 200 + len(self.release['assets']), 'name': name, 'state': 'uploaded',
                 'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}
        self.release['assets'].append(asset)
        return copy.deepcopy(asset)

    def download(self, asset_id, path):
        self.calls.append(('DOWNLOAD', asset_id))
        asset = next(a for a in self.release['assets'] if a['id'] == asset_id)
        Path(path).write_bytes(self.files[asset['name']])

    def mutations(self):
        return [c for c in self.calls if c[0] in ('PATCH', 'POST', 'UPLOAD')]

