"""Small GitHub CLI boundary; release logic is independently testable offline."""
import json
import os
import subprocess
from urllib.parse import quote


class GitHub:
    def __init__(self, repository, token):
        if repository not in ('CraftedSignal/platform', 'CraftedSignal/releases') or not token:
            raise ValueError('Release repository and token are required')
        self.repository = repository
        self.env = dict(os.environ, GH_TOKEN=token, GH_HOST='github.com')

    def _command(self, method, path):
        return ['gh', 'api', '--hostname', 'github.com', '--method', method,
                '-H', 'X-GitHub-Api-Version: 2022-11-28', path]

    def _request(self, method, path, data=None):
        command = self._command(method, '/repos/' + self.repository + path)
        payload = None
        if data is not None:
            command += ['--input', '-']
            payload = json.dumps(data).encode()
        result = subprocess.run(command, input=payload, env=self.env, capture_output=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def get(self, path):
        return self._request('GET', path)

    def post(self, path, data):
        return self._request('POST', path, data)

    def patch(self, path, data):
        return self._request('PATCH', path, data)

    def download(self, asset_id, path):
        command = self._command('GET', f'/repos/{self.repository}/releases/assets/{asset_id}')
        command += ['-H', 'Accept: application/octet-stream']
        with path.open('wb') as stream:
            subprocess.run(command, env=self.env, stdout=stream, stderr=subprocess.PIPE, check=True)

    def upload(self, release_id, name, path):
        url = f'https://uploads.github.com/repos/{self.repository}/releases/{release_id}/assets?name={quote(name, safe="")}'
        command = self._command('POST', url) + ['-H', 'Content-Type: application/octet-stream', '--input', str(path)]
        result = subprocess.run(command, env=self.env, capture_output=True, check=True)
        return json.loads(result.stdout)
