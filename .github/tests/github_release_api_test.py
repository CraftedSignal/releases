"""Exercise the real subprocess boundary using a local, network-free gh executable."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from release_assets_test import load


class GitHubReleaseAPITest(unittest.TestCase):
    def test_requests_download_and_upload_preserve_bytes_and_token_scope(self):
        module = load('github_release_api')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'gh'
            executable.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
payload = sys.stdin.buffer.read() if '--input' in args and args[args.index('--input')+1] == '-' else b''
with pathlib.Path(os.environ['TEST_API_LOG']).open('a') as log:
    log.write(json.dumps({'args': args, 'payload': payload.decode(), 'token': os.environ['GH_TOKEN']}) + '\\n')
if 'Accept: application/octet-stream' in args:
    sys.stdout.buffer.write(b'archive\\x00bytes')
elif 'Content-Type: application/octet-stream' in args:
    data = pathlib.Path(args[args.index('--input')+1]).read_bytes()
    print(json.dumps({'size': len(data)}))
else:
    print(json.dumps({'ok': True}))
''')
            executable.chmod(0o755)
            log = root / 'api.jsonl'
            with patch.dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'], TEST_API_LOG=str(log)):
                source = module.GitHub('CraftedSignal/platform', 'dummy-source-token')
                destination = module.GitHub('CraftedSignal/releases', 'dummy-target-token')
                self.assertEqual({'ok': True}, source.get('/releases/10'))
                destination.post('/releases', {'draft': True, 'body': 'Literal $() and ` text\n'})
                destination.patch('/releases/20', {'draft': False})
                path = root / 'archive.bin'
                source.download(100, path)
                self.assertEqual(b'archive\x00bytes', path.read_bytes())
                self.assertEqual({'size': 13}, destination.upload(20, 'safe name.zip', path))
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(['dummy-source-token', 'dummy-target-token', 'dummy-target-token', 'dummy-source-token', 'dummy-target-token'], [r['token'] for r in records])
            self.assertEqual(['GET', 'POST', 'PATCH', 'GET', 'POST'], [r['args'][r['args'].index('--method') + 1] for r in records])
            self.assertEqual({'draft': True, 'body': 'Literal $() and ` text\n'}, json.loads(records[1]['payload']))
            self.assertIn('/repos/CraftedSignal/platform/releases/assets/100', records[3]['args'])
            self.assertIn('https://uploads.github.com/repos/CraftedSignal/releases/releases/20/assets?name=safe%20name.zip', records[4]['args'])

    def test_tokens_cannot_target_an_unrelated_repository(self):
        module = load('github_release_api')
        with self.assertRaises(ValueError):
            module.GitHub('somewhere/else', 'dummy')


if __name__ == '__main__':
    unittest.main()
