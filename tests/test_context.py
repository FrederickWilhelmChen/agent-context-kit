import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_context_kit import cli as module


def record(text, role='user'):
    return json.dumps({'type': role, 'sessionId': 'native-1', 'cwd': '/projects/demo',
                       'timestamp': '2026-11-05T10:00:00Z',
                       'message': {'role': role, 'content': text}}, ensure_ascii=False).encode() + b'\n'


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / 'home'
        self.root = Path(self.temp.name) / 'context'
        self.path = self.home / '.claude/projects/demo/session.jsonl'
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(record('测试中文记忆 100%_test'))
        self.db = module.connect(self.root)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def sync(self):
        return module.sync(self.db, self.root, self.home)

    def texts(self):
        return [r[0] for r in self.db.execute('SELECT text FROM messages ORDER BY id')]

    def cli(self, *args):
        result = subprocess.run([sys.executable, '-m', 'agent_context_kit.cli', '--root', str(self.root),
                                 '--source-home', str(self.home), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_append_idempotent_partial_and_rewrite(self):
        self.assertEqual(self.sync()['rebuilt'], 1)
        self.assertEqual(self.sync()['unchanged'], 1)
        chunk = record('下一条')
        with self.path.open('ab') as f:
            f.write(chunk[:15])
        self.assertEqual(self.sync()['messages_added'], 0)
        with self.path.open('ab') as f:
            f.write(chunk[15:])
        self.assertEqual(self.sync()['messages_added'], 1)
        self.assertEqual(len(self.texts()), 2)
        self.path.write_bytes(record('改写的历史') + record('追加'))
        self.assertEqual(self.sync()['rebuilt'], 1)
        self.assertEqual(self.texts(), ['改写的历史', '追加'])
        self.path.write_bytes(record('截断'))
        self.sync()
        self.assertEqual(self.texts(), ['截断'])
        self.assertEqual(len(self.cli('search', '测试')['results']), 0)

    def test_chinese_literals_pagination_raw_and_deletion(self):
        self.path.write_bytes(record('测试中文记忆 100%_test') + record('第二条中文记忆'))
        result = self.cli('search', '中文记忆', '--limit', '1')
        self.assertEqual(result['next_offset'], 1)
        self.assertEqual(len(self.cli('search', '中文记忆', '--offset', '1')['results']), 1)
        self.assertEqual(len(self.cli('search', '中文')['results']), 2)
        self.assertEqual(len(self.cli('search', '100%_')['results']), 1)
        sid = result['results'][0]['id']
        raw = self.cli('read', sid, '--raw', '--start-line', '2')['messages'][0]
        self.assertEqual(json.loads(raw['text'])['message']['content'], '第二条中文记忆')
        small = self.cli('read', sid, '--max-chars', '2')
        self.assertTrue(small['messages'][0]['truncated'])
        self.path.unlink()
        self.assertEqual(self.cli('list')['total'], 0)
        self.assertEqual(len(self.cli('search', '中文')['results']), 0)
        self.assertEqual(self.db.execute('SELECT available FROM sources').fetchone()[0], 0)

    def test_codex_tools_duplicates_and_compression(self):
        import zstandard
        p = self.home / '.codex/archived_sessions/rollout.jsonl.zst'
        p.parent.mkdir(parents=True)
        events = [
            {'type': 'session_meta', 'payload': {'id': 'codex-native', 'cwd': '/project/codex'}},
            {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': '镜像不重复'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '镜像不重复'}]}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'output': '工具证据'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '已完成'}]}},
        ]
        payload = b''.join((json.dumps(x, ensure_ascii=False) + '\n').encode() for x in events)
        p.write_bytes(zstandard.ZstdCompressor().compress(payload))
        self.assertEqual(self.sync()['rebuilt'], 2)
        self.assertEqual(self.texts().count('镜像不重复'), 1)
        self.assertNotIn('工具证据', self.texts())
        sid = self.cli('list', '--provider', 'codex')['sessions'][0]['id']
        raw = self.cli('read', sid, '--raw', '--start-line', '4', '--limit', '1')
        self.assertIn('工具证据', raw['messages'][0]['text'])
        self.assertEqual(self.sync()['unchanged'], 2)

    def test_memory_maps_do_not_copy_or_overwrite(self):
        memory = self.path.parent / 'memory'
        memory.mkdir()
        (memory / 'MEMORY.md').write_text('明确偏好')
        self.sync()
        mapping = self.root / 'memory/imported/claude-demo'
        self.assertTrue(mapping.is_symlink())
        self.assertEqual(mapping.resolve(), memory.resolve())
        (self.root / 'memory/shared/preference.md').write_text('共享偏好')
        self.assertEqual(self.cli('memory', '--query', '偏好')['total'], 2)
        self.assertEqual((memory / 'MEMORY.md').read_text(), '明确偏好')

    def test_invalid_record_reported_until_fixed(self):
        self.path.write_bytes(record('valid') + b'{bad}\n')
        self.sync()
        self.assertTrue(self.db.execute('SELECT error FROM sources').fetchone()[0])
        self.sync()
        self.assertTrue(self.db.execute('SELECT error FROM sources').fetchone()[0])
        self.path.write_bytes(record('fixed'))
        self.sync()
        self.assertEqual(self.db.execute('SELECT error FROM sources').fetchone()[0], '')
        self.assertEqual(self.texts(), ['fixed'])

    def test_concurrent_sync_has_no_duplicate_messages(self):
        self.db.close()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.cli('sync'), range(2)))
        self.db = module.connect(self.root)
        self.assertEqual(len(self.texts()), 1)
        self.assertEqual(sum(r['messages_added'] for r in results), 1)


if __name__ == '__main__':
    unittest.main()
