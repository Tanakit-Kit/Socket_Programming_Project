import os
import tempfile
import unittest
import json
from pathlib import Path
for line in Path('.env.template').read_text().splitlines():
    if line and not line.startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key, value)
import server

class Socket:
    def __init__(self): self.messages = []
    async def send(self, value): self.messages.append(json.loads(value))

class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_bot_history_and_group_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            server.DB_FILE = str(Path(directory) / 'chat.db')
            server.init_db()
            a, b = Socket(), Socket()
            server.clients.clear()
            await server.handle_register(a, None, {'username': 'alice'})
            await server.handle_register(b, None, {'username': 'bob'})
            server.call_gemini_api = lambda question, history: 'reply'
            await server.handle_bot(a, 'alice', {'type': 'private_msg', 'target': 'bob', 'message': '/bot hello'})
            self.assertEqual(a.messages[-1]['peer'], 'bob')
            self.assertEqual(b.messages[-1]['peer'], 'alice')
            history = server.get_private_history('alice', 'bob')
            self.assertEqual([m['sender'] for m in history], ['alice', 'GeminiBot'])
            self.assertEqual(server.get_private_history('alice', 'charlie'), [])
            await server.handle_create_group(a, 'alice', {'group_name': 'room:one'})
            await server.handle_bot(a, 'alice', {'type': 'group_msg', 'group_name': 'room:one', 'message': '/bot hi'})
            server.init_db()
            self.assertIn('alice', server.groups['room:one'])
            self.assertEqual(server.get_group_history('room:one')[-1]['sender'], 'GeminiBot')

    async def test_user_directory_survives_disconnect_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            server.DB_FILE = str(Path(directory) / 'chat.db')
            server.clients.clear()
            server.init_db()
            a, b = Socket(), Socket()
            await server.handle_register(a, None, {'username': 'alice'})
            await server.handle_register(b, None, {'username': 'bob'})
            del server.clients['bob']
            await server.broadcast_user_list()
            self.assertEqual(a.messages[-1]['users'], ['alice'])
            self.assertEqual(a.messages[-1]['all_users'], ['alice', 'bob'])
            server.clients.clear()
            server.init_db()
            await server.handle_register(a, None, {'username': 'alice'})
            directory_message = next(m for m in reversed(a.messages) if m['type'] == 'user_list')
            self.assertEqual(directory_message['all_users'], ['alice', 'bob'])
            self.assertEqual(directory_message['users'], ['alice'])
