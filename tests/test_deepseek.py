import json
from pathlib import Path
import tempfile
import unittest
import zstandard

from agent_context_kit import cli as context


def event(kind, text, source='user'):
    message = {'role': kind.split('/')[0], 'source': {'kind': source},
               'content': [{'type': 'text', 'text': text}, {'type': 'reasoning', 'text': 'private reasoning'}]}
    return {'type': kind, 'time': 1793836800000,
            'data': {'message': message} if kind == 'assistant/message' else message}


class DeepSeekTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)/'home'
        self.root = Path(self.tmp.name)/'index'
        self.path = self.home/'.dsh/sessions/workspace/worker-one/session.v4.jsonl.zstd'
        self.path.parent.mkdir(parents=True)
        self.events = [{'type':'session','version':4,'id':'worker-one','cwd':'/project'},
                       {'type':'session/title','data':{'title':'中文历史'}},
                       event('user/message','真实用户请求'),
                       event('user/message','协调者转发','dsh-superagent'),
                       event('user/message','运行时提示','runtime-context'),
                       event('assistant/message','最终答复','model'),
                       {'type':'text-chunks','data':{'texts':['最终答复']}},
                       {'type':'tool/result','data':{'evidence':'工具结果'}}]
        self.db = context.connect(self.root)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def encode(self, events):
        return b''.join((json.dumps(e,ensure_ascii=False)+'\n').encode() for e in events)

    def sync(self):
        return context.sync(self.db,self.root,self.home)

    def test_compressed_frames_roles_rewrite_and_raw(self):
        self.path.write_bytes(zstandard.ZstdCompressor().compress(self.encode(self.events)))
        self.assertEqual(self.sync()['rebuilt'],1)
        self.assertEqual(self.sync()['unchanged'],1)
        rows=self.db.execute('SELECT role,text FROM messages ORDER BY line').fetchall()
        self.assertEqual([(r['role'],r['text']) for r in rows],
                         [('user','真实用户请求'),('agent','协调者转发'),('assistant','最终答复')])
        with self.path.open('ab') as f:
            f.write(zstandard.ZstdCompressor().compress(self.encode([event('assistant/message','追加答复','model')])) )
        self.sync()
        self.assertEqual(self.db.execute('SELECT count(*) FROM messages').fetchone()[0],4)
        with context.stream(self.path) as f:
            raw=[json.loads(line) for line in f]
        self.assertEqual(raw[7]['data']['evidence'],'工具结果')
        self.path.write_bytes(zstandard.ZstdCompressor().compress(self.encode(self.events[:3])))
        self.sync()
        self.assertEqual(self.db.execute('SELECT count(*) FROM messages').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM search WHERE text LIKE '%追加答复%'").fetchone()[0],0)

    def test_legacy_plain_append_and_metadata(self):
        self.path=self.path.with_name('session.jsonl')
        self.path.write_bytes(self.encode(self.events))
        self.sync()
        with self.path.open('ab') as f:
            f.write(self.encode([event('assistant/message','新增','model')]))
        self.assertEqual(self.sync()['appended'],1)
        row=self.db.execute('SELECT * FROM sources').fetchone()
        self.assertEqual((row['native_id'],row['project'],row['title']),('worker-one','/project','中文历史'))
        self.path.unlink()
        self.sync()
        self.assertEqual(self.db.execute('SELECT available FROM sources').fetchone()[0],0)


if __name__=='__main__':
    unittest.main()
