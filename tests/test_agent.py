import asyncio
import os
import sqlite3
import tempfile
import time
import unittest
import json
from pathlib import Path
for line in Path('.env.template').read_text().splitlines():
    if line and not line.startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key, value)
import server
from agent_service import should_wake


class Socket:
    def __init__(self, incoming=()):
        self.messages = []
        self.incoming = list(incoming)
    async def send(self, value): self.messages.append(json.loads(value))
    def __aiter__(self): return self._iterate()
    async def _iterate(self):
        for item in self.incoming:
            yield json.dumps(item)


def call(name, **args):
    return {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}

def say(text):
    return {"role": "model", "parts": [{"text": text}]}


class Gemini:
    """จำลอง Gemini: คืนผลตามลำดับที่กำหนด และเก็บการเรียกไว้ตรวจ"""
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
    def __call__(self, system, contents, tools):
        self.calls.append({"system": system, "contents": list(contents), "tools": [t["name"] for t in tools]})
        return self.replies.pop(0) if self.replies else say("")


def of_type(socket, kind):
    return [m for m in socket.messages if m["type"] == kind]


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.originals = (server.DB_FILE, server.AGENT_DEBOUNCE_SECONDS, server.AGENT_MAX_RUNS_PER_MINUTE,
                          server.AGENT_MAX_STEPS, server.call_gemini_with_tools)
        server.DB_FILE = str(Path(self.directory.name) / 'chat.db')
        server.AGENT_DEBOUNCE_SECONDS = 0
        server.AGENT_MAX_RUNS_PER_MINUTE = 100
        for registry in (server.clients, server.groups, server.agent_pending, server.agent_running, server.agent_run_times):
            registry.clear()
        server.init_db()
        self.alice, self.bob, self.carol = Socket(), Socket(), Socket()
        await server.handle_register(self.alice, None, {'username': 'alice'})
        await server.handle_register(self.bob, None, {'username': 'bob'})
        await server.handle_register(self.carol, None, {'username': 'carol'})
        await server.handle_create_group(self.alice, 'alice', {'group_name': 'team'})
        await server.handle_join_group(self.bob, 'bob', {'group_name': 'team'})

    async def asyncTearDown(self):
        for owner in ('alice', 'bob', 'carol'):
            server.cancel_owner_agents(owner)
        await asyncio.sleep(0)
        (server.DB_FILE, server.AGENT_DEBOUNCE_SECONDS, server.AGENT_MAX_RUNS_PER_MINUTE,
         server.AGENT_MAX_STEPS, server.call_gemini_with_tools) = self.originals
        self.directory.cleanup()

    async def settle(self):
        for _ in range(200):
            await asyncio.sleep(0.005)
            if not server.agent_pending and not server.agent_running:
                return
        self.fail("agent tasks did not finish")

    async def set_mode(self, mode, owner='alice', socket=None, room_type='group', room='team'):
        await server.handle_agent_set_mode(socket or self.alice, owner,
                                           {'room_type': room_type, 'room': room, 'mode': mode})

    async def invoke(self, instruction='ช่วยตอบ', owner='alice', socket=None, room_type='group', room='team'):
        await server.handle_agent_invoke(socket or self.alice, owner,
                                         {'room_type': room_type, 'room': room, 'instruction': instruction})
        await self.settle()

    async def bob_says(self, text):
        msg = {'type': 'group_msg', 'group_name': 'team', 'message': text}
        await server.handle_group_msg(self.bob, 'bob', msg)
        server.schedule_agents('bob', msg)

    def group_senders(self):
        return [m['sender'] for m in server.get_group_history('team')]

    async def test_auto_posts_immediately_to_members_only(self):
        server.call_gemini_with_tools = Gemini(call('post_message', text='สวัสดี'), say('เสร็จแล้ว'))
        await self.set_mode('auto')
        await self.invoke()
        self.assertEqual(self.group_senders(), ['alice'])
        delivered = of_type(self.bob, 'group_msg')[-1]
        self.assertEqual((delivered['sender'], delivered['agent']), ('alice', True))
        self.assertEqual(of_type(self.carol, 'group_msg'), [])

    async def test_advice_for_owner_stays_private_in_auto(self):
        server.call_gemini_with_tools = Gemini(call('propose_to_owner', summary='ควรถามกลับ', options=['แล้วคุณล่ะ']))
        await self.set_mode('auto')
        await self.invoke('ควรตอบอะไรดี')
        self.assertEqual(self.group_senders(), [])
        self.assertEqual(of_type(self.bob, 'agent_proposal'), [])
        proposal = of_type(self.alice, 'agent_proposal')[-1]
        self.assertEqual((proposal['kind'], proposal['summary'], proposal['options']), ('choices', 'ควรถามกลับ', ['แล้วคุณล่ะ']))

    async def make_draft(self, text='ร่าง'):
        """Manual: สั่งงาน เลือกแนวทางแรก แล้วได้ฉบับร่าง"""
        server.call_gemini_with_tools = Gemini(call('propose_to_owner', summary='สรุป', options=['แนวทาง']), call('post_message', text=text))
        await self.set_mode('manual')
        await self.invoke()
        choices = of_type(self.alice, 'agent_proposal')[-1]
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': choices['proposal_id'], 'decision': 'choose', 'option': 0})
        await self.settle()
        return of_type(self.alice, 'agent_proposal')[-1]

    async def test_auto_answers_by_itself_on_incoming_message(self):
        gemini = Gemini(call('post_message', text='ตอบเอง'), say(''))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto')
        await self.bob_says('alice ชอบทำอะไร?')
        await self.settle()
        self.assertNotIn('propose_to_owner', gemini.calls[0]['tools'])
        self.assertIn('post_message', gemini.calls[0]['tools'])
        self.assertEqual(server.get_group_history('team')[-1]['message'], 'ตอบเอง')
        self.assertEqual(server.get_group_history('team')[-1]['sender'], 'alice')
        self.assertEqual(of_type(self.alice, 'agent_proposal'), [])

    async def test_manual_offers_approaches_on_incoming_and_cannot_post(self):
        gemini = Gemini(call('post_message', text='แอบส่ง'), call('propose_to_owner', summary='s', options=['ถามกลับ']))
        server.call_gemini_with_tools = gemini
        await self.set_mode('manual')
        await self.bob_says('alice ชอบทำอะไร?')
        await self.settle()
        self.assertNotIn('post_message', gemini.calls[0]['tools'])
        self.assertIn('no_reply', gemini.calls[0]['tools'])
        self.assertEqual(self.group_senders(), ['bob'])
        proposal = of_type(self.alice, 'agent_proposal')[-1]
        self.assertEqual((proposal['kind'], proposal['options']), ('choices', ['ถามกลับ']))

    async def test_plan_mode_no_longer_exists(self):
        await self.set_mode('plan')
        self.assertEqual(server.get_agent_mode('alice', 'group', 'team'), 'off')
        self.assertIn('ตั้งค่า Agent', of_type(self.alice, 'agent_error')[-1]['message'])

    async def test_saved_plan_mode_becomes_manual(self):
        server.set_agent_mode('alice', 'group', 'team', 'plan')
        server.init_db()
        self.assertEqual(server.get_agent_mode('alice', 'group', 'team'), 'manual')

    async def test_auto_stops_after_one_message_with_one_ai_call(self):
        both = {"role": "model", "parts": [{"functionCall": {"name": "post_message", "args": {"text": "หนึ่ง"}}},
                                           {"functionCall": {"name": "post_message", "args": {"text": "สอง"}}}]}
        gemini = Gemini(both, call('post_message', text='สาม'))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto')
        await self.invoke()
        self.assertEqual(len(gemini.calls), 1)
        self.assertEqual([m['message'] for m in server.get_group_history('team')], ['หนึ่ง'])

    async def test_rate_limited_wakeup_tells_the_owner(self):
        gemini = Gemini(call('post_message', text='ไม่ควรส่ง'))
        server.call_gemini_with_tools = gemini
        server.AGENT_MAX_RUNS_PER_MINUTE = 0
        await self.set_mode('auto')
        await self.bob_says('alice อยู่ไหม')
        await self.settle()
        self.assertEqual(gemini.calls, [])
        self.assertIn('ถี่เกินไป', of_type(self.alice, 'agent_error')[-1]['message'])
        self.assertEqual(of_type(self.bob, 'agent_error'), [])

    async def test_manual_requires_approval_and_draft_is_private(self):
        proposal = await self.make_draft()
        self.assertEqual(self.group_senders(), [])
        self.assertEqual((proposal['kind'], proposal['text']), ('draft', 'ร่าง'))
        self.assertEqual(of_type(self.bob, 'agent_proposal'), [])
        self.assertEqual(of_type(self.bob, 'group_msg'), [])
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': proposal['proposal_id'], 'decision': 'approve', 'text': 'แก้แล้ว'})
        self.assertEqual(server.get_group_history('team')[-1]['message'], 'แก้แล้ว')
        self.assertEqual(of_type(self.bob, 'group_msg')[-1]['message'], 'แก้แล้ว')
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': proposal['proposal_id'], 'decision': 'approve'})
        self.assertEqual(len(self.group_senders()), 1)

    async def choose(self, proposal, option):
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': proposal['proposal_id'], 'decision': 'choose', 'option': option})
        await self.settle()

    async def test_choosing_an_approach_writes_a_draft_before_anything_is_sent(self):
        gemini = Gemini(call('post_message', text='ห้ามส่ง'),
                        call('propose_to_owner', summary='สรุปถึงเจ้าของ', options=['ถามกลับ', 'เล่าเรื่องตัวเอง']),
                        call('post_message', text='แล้วคุณล่ะครับ'))
        server.call_gemini_with_tools = gemini
        await self.set_mode('manual')
        await self.invoke('ช่วยคิด')
        self.assertEqual(self.group_senders(), [])
        self.assertNotIn('post_message', gemini.calls[0]['tools'])
        choices = of_type(self.alice, 'agent_proposal')[-1]
        self.assertEqual((choices['kind'], choices['options']), ('choices', ['ถามกลับ', 'เล่าเรื่องตัวเอง']))
        self.assertNotIn('instruction', choices)

        await self.choose(choices, 0)
        self.assertEqual(self.group_senders(), [])
        writing = gemini.calls[2]
        self.assertIn('ถามกลับ', writing['contents'][0]['parts'][0]['text'])
        self.assertNotIn('เล่าเรื่องตัวเอง\nเขียน', writing['contents'][0]['parts'][0]['text'])
        self.assertNotIn('propose_to_owner', writing['tools'])
        draft = of_type(self.alice, 'agent_proposal')[-1]
        self.assertEqual((draft['kind'], draft['text'], draft['can_go_back']), ('draft', 'แล้วคุณล่ะครับ', True))
        self.assertNotIn('origin', draft)
        self.assertEqual(of_type(self.bob, 'agent_proposal'), [])
        closed = of_type(self.alice, 'agent_proposal_closed')[-1]
        self.assertEqual((closed['proposal_id'], closed['status']), (choices['proposal_id'], 'superseded'))

        calls_before = len(gemini.calls)
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': draft['proposal_id'], 'decision': 'approve', 'text': 'แล้วคุณล่ะ'})
        await self.settle()
        self.assertEqual(len(gemini.calls), calls_before)
        history = server.get_group_history('team')
        self.assertEqual([(m['sender'], m['message']) for m in history], [('alice', 'แล้วคุณล่ะ')])

    async def test_choosing_an_approach_in_auto_still_makes_a_draft(self):
        server.call_gemini_with_tools = Gemini(call('propose_to_owner', summary='s', options=['ถามกลับ']), call('post_message', text='ประโยค'))
        await self.set_mode('auto')
        await self.invoke()
        await self.choose(of_type(self.alice, 'agent_proposal')[-1], 0)
        self.assertEqual(self.group_senders(), [])
        self.assertEqual(of_type(self.alice, 'agent_proposal')[-1]['kind'], 'draft')

    async def test_go_back_restores_approaches_without_ai_call(self):
        gemini = Gemini(call('propose_to_owner', summary='สรุป', options=['ก', 'ข']), call('post_message', text='ประโยค ก'), call('post_message', text='ประโยค ข'))
        server.call_gemini_with_tools = gemini
        await self.set_mode('manual')
        await self.invoke()
        await self.choose(of_type(self.alice, 'agent_proposal')[-1], 0)
        draft = of_type(self.alice, 'agent_proposal')[-1]
        calls_before = len(gemini.calls)
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': draft['proposal_id'], 'decision': 'back'})
        self.assertEqual(len(gemini.calls), calls_before)
        restored = of_type(self.alice, 'agent_proposal')[-1]
        self.assertEqual((restored['kind'], restored['options'], restored['can_go_back']), ('choices', ['ก', 'ข'], False))
        await self.choose(restored, 1)
        self.assertEqual(of_type(self.alice, 'agent_proposal')[-1]['text'], 'ประโยค ข')
        self.assertEqual(self.group_senders(), [])

    async def test_failed_writing_keeps_approaches_available(self):
        replies = iter([call('propose_to_owner', summary='s', options=['ก'])])
        def flaky(system, contents, tools):
            reply = next(replies, None)
            if reply is None:
                raise server.GeminiError('โควตาหมด')
            return reply
        server.call_gemini_with_tools = flaky
        await self.set_mode('manual')
        await self.invoke()
        choices = of_type(self.alice, 'agent_proposal')[-1]
        await self.choose(choices, 0)
        self.assertEqual(of_type(self.alice, 'agent_error')[-1]['message'], 'โควตาหมด')
        self.assertEqual(of_type(self.alice, 'agent_proposal_closed'), [])
        server.call_gemini_with_tools = Gemini(call('post_message', text='สำเร็จ'))
        await self.choose(choices, 0)
        self.assertEqual(of_type(self.alice, 'agent_proposal')[-1]['text'], 'สำเร็จ')

    async def test_invalid_choices_are_rejected(self):
        gemini = Gemini(call('propose_to_owner', summary='สรุป', options=['ก']))
        server.call_gemini_with_tools = gemini
        await self.set_mode('manual')
        await self.invoke()
        proposal = of_type(self.alice, 'agent_proposal')[-1]
        for option in (5, -1, True, 'ก', None):
            await self.choose(proposal, option)
            self.assertIn('ไม่พบแนวทาง', of_type(self.alice, 'agent_error')[-1]['message'])
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': proposal['proposal_id'], 'decision': 'approve', 'text': 'แอบส่ง'})
        self.assertEqual(self.group_senders(), [])
        self.assertEqual(len(gemini.calls), 1)
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': proposal['proposal_id'], 'decision': 'reject'})
        self.assertEqual(of_type(self.alice, 'agent_proposal_closed')[-1]['status'], 'rejected')

    async def test_revise_starts_new_proposal_and_can_never_post(self):
        gemini = Gemini(call('propose_to_owner', summary='แรก'), call('propose_to_owner', summary='สอง'))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto')
        await self.invoke()
        first = of_type(self.alice, 'agent_proposal')[-1]
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': first['proposal_id'], 'decision': 'revise', 'text': 'สั้นลง'})
        await self.settle()
        self.assertEqual(of_type(self.alice, 'agent_proposal')[-1]['summary'], 'สอง')
        self.assertIn('สั้นลง', gemini.calls[1]['contents'][0]['parts'][0]['text'])
        self.assertNotIn('post_message', gemini.calls[1]['tools'])
        self.assertEqual(self.group_senders(), [])

    async def test_other_user_cannot_decide(self):
        proposal = await self.make_draft()
        await server.handle_agent_decide(self.bob, 'bob', {'proposal_id': proposal['proposal_id'], 'decision': 'approve'})
        self.assertEqual(self.group_senders(), [])
        self.assertEqual(of_type(self.bob, 'agent_error')[-1]['message'], 'รายการนี้ถูกปิดไปแล้ว')

    async def test_tools_only_see_current_room(self):
        await server.handle_group_msg(self.alice, 'alice', {'group_name': 'team', 'message': 'ความลับกลุ่ม'})
        await server.handle_private_msg(self.bob, 'bob', {'target': 'carol', 'message': 'ความลับคู่อื่น'})
        gemini = Gemini(call('read_recent_messages', limit=50), say(''))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto', room_type='private', room='bob')
        await self.invoke(room_type='private', room='bob')
        response = gemini.calls[1]['contents'][-1]['parts'][0]['functionResponse']['response']
        self.assertEqual(response, {'messages': []})

    async def test_non_member_cannot_use_agent_in_group(self):
        gemini = Gemini(say('ไม่ควรถูกเรียก'))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto', owner='carol', socket=self.carol)
        await self.invoke(owner='carol', socket=self.carol)
        self.assertEqual(gemini.calls, [])
        self.assertEqual(server.get_agent_mode('carol', 'group', 'team'), 'off')
        self.assertEqual(server.agent_room_history('carol', 'group', 'team'), [])

    async def test_ai_messages_do_not_wake_other_agents(self):
        gemini = Gemini(call('post_message', text='ตอบ?'), say(''))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto')
        await self.set_mode('auto', owner='bob', socket=self.bob)
        await self.invoke()
        await self.settle()
        self.assertEqual(self.group_senders(), ['alice'])
        self.assertEqual(len(gemini.calls), 1)
        self.assertEqual(server.agent_pending, {})

    async def test_filter_skips_plain_group_message_and_wakes_on_question(self):
        gemini = Gemini(call('no_reply', reason='ไม่เกี่ยว'), call('post_message', text='ตอบแล้ว'), say(''))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto')
        await self.bob_says('ทานข้าวแล้ว')
        await self.settle()
        self.assertEqual(gemini.calls, [])
        await self.bob_says('alice อยู่ไหม')
        await self.settle()
        self.assertEqual(len(gemini.calls), 1)
        self.assertIn('no_reply', gemini.calls[0]['tools'])
        self.assertEqual(self.group_senders(), ['bob', 'bob'])
        await self.bob_says('นัดกี่โมง?')
        await self.settle()
        self.assertEqual(server.get_group_history('team')[-1]['sender'], 'alice')
        self.assertEqual(server.get_group_history('team')[-1]['message'], 'ตอบแล้ว')

    async def test_debounce_merges_messages_into_one_run(self):
        gemini = Gemini(call('no_reply', reason='ok'))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto')
        await self.bob_says('alice หนึ่ง')
        await self.bob_says('alice สอง')
        await self.bob_says('alice สาม')
        await self.settle()
        self.assertEqual(len(gemini.calls), 1)

    async def test_handler_wakes_on_human_message_but_not_bot_command(self):
        gemini = Gemini(call('no_reply', reason='ok'))
        server.call_gemini_with_tools = gemini
        server.call_gemini_api = lambda question, history: 'reply'
        await self.set_mode('auto')
        del server.clients['bob']
        socket = Socket([
            {'type': 'register', 'username': 'bob'},
            {'type': 'group_msg', 'group_name': 'team', 'message': '/bot alice ช่วยหน่อย?'},
        ])
        await server.handler(socket)
        await self.settle()
        self.assertEqual(gemini.calls, [])
        self.assertEqual(self.group_senders()[-1], 'GeminiBot')

        server.clients['alice'] = self.alice
        socket = Socket([
            {'type': 'register', 'username': 'bob'},
            {'type': 'group_msg', 'group_name': 'team', 'message': 'alice ช่วยหน่อย?'},
        ])
        await server.handler(socket)
        await self.settle()
        self.assertEqual(len(gemini.calls), 1)

    async def test_step_and_rate_limits(self):
        server.AGENT_MAX_STEPS = 2
        gemini = Gemini(call('read_recent_messages'), call('read_recent_messages'), call('read_recent_messages'))
        server.call_gemini_with_tools = gemini
        await self.set_mode('auto')
        await self.invoke()
        self.assertEqual(len(gemini.calls), 2)
        self.assertIn('ครบจำนวนรอบ', of_type(self.alice, 'agent_error')[-1]['message'])

        server.AGENT_MAX_RUNS_PER_MINUTE = 1
        gemini = Gemini(say(''))
        server.call_gemini_with_tools = gemini
        await self.invoke()
        self.assertEqual(gemini.calls, [])
        self.assertIn('ถี่เกินไป', of_type(self.alice, 'agent_error')[-1]['message'])

    async def test_agent_messages_use_owner_name_without_new_user_after_restart(self):
        server.call_gemini_with_tools = Gemini(call('post_message', text='สวัสดี'), say(''))
        await self.set_mode('auto')
        await self.invoke()
        server.init_db()
        with sqlite3.connect(server.DB_FILE) as conn:
            users = sorted(row[0] for row in conn.execute("SELECT username FROM users"))
        self.assertEqual(users, ['alice', 'bob', 'carol'])
        self.assertEqual(self.group_senders(), ['alice'])

    async def test_private_agent_reply_uses_owner_name_with_correct_peers(self):
        server.call_gemini_with_tools = Gemini(call('post_message', text='ตอบ'), say(''))
        await self.set_mode('auto', room_type='private', room='bob')
        await self.invoke(room_type='private', room='bob')
        to_alice = of_type(self.alice, 'private_msg')[-1]
        to_bob = of_type(self.bob, 'private_msg')[-1]
        self.assertEqual((to_alice['sender'], to_alice['peer'], to_alice['agent']), ('alice', 'bob', True))
        self.assertEqual((to_bob['sender'], to_bob['peer'], to_bob['agent']), ('alice', 'alice', True))
        self.assertEqual(server.get_private_history('alice', 'bob')[-1]['sender'], 'alice')

    async def test_bot_name_is_reserved(self):
        socket = Socket()
        self.assertIsNone(await server.handle_register(socket, None, {'username': 'GeminiBot'}))
        self.assertFalse(socket.messages[-1]['success'])
        self.assertNotIn('GeminiBot', server.clients)

    async def test_plain_text_is_shown_only_to_owner(self):
        server.call_gemini_with_tools = Gemini(say('คำตอบที่ไม่ได้เรียกเครื่องมือ'))
        await self.set_mode('auto')
        await self.invoke()
        self.assertEqual(self.group_senders(), [])
        proposal = of_type(self.alice, 'agent_proposal')[-1]
        self.assertEqual((proposal['summary'], proposal['options']), ('คำตอบที่ไม่ได้เรียกเครื่องมือ', []))

    async def test_gemini_error_only_reaches_owner(self):
        def fail(system, contents, tools):
            raise server.GeminiError('โควตาหมด')
        server.call_gemini_with_tools = fail
        await self.set_mode('auto')
        await self.invoke()
        self.assertEqual(self.group_senders(), [])
        self.assertEqual(of_type(self.alice, 'agent_error')[-1]['message'], 'โควตาหมด')
        self.assertEqual(of_type(self.bob, 'agent_error'), [])
        self.assertEqual(of_type(self.alice, 'agent_state')[-1]['status'], 'idle')

    async def test_turning_off_cancels_run_and_closes_proposals(self):
        proposal = await self.make_draft()

        def slow(system, contents, tools):
            time.sleep(0.05)
            return call('post_message', text='สายเกินไป')
        server.call_gemini_with_tools = slow
        await self.set_mode('auto')
        await server.handle_agent_invoke(self.alice, 'alice', {'room_type': 'group', 'room': 'team', 'instruction': 'x'})
        self.assertIn(('alice', 'group', 'team'), server.agent_running)
        await self.set_mode('off')
        self.assertNotIn(('alice', 'group', 'team'), server.agent_running)
        await asyncio.sleep(0.1)
        self.assertEqual(self.group_senders(), [])
        closed = of_type(self.alice, 'agent_proposal_closed')[-1]
        self.assertEqual((closed['proposal_id'], closed['status']), (proposal['proposal_id'], 'cancelled'))

    async def test_disconnect_cancels_and_register_restores_state(self):
        await self.make_draft()
        del server.clients['alice']
        server.cancel_owner_agents('alice')
        socket = Socket()
        await server.handle_register(socket, None, {'username': 'alice'})
        self.assertEqual(of_type(socket, 'agent_state')[-1]['mode'], 'manual')
        self.assertEqual(of_type(socket, 'agent_proposal')[-1]['text'], 'ร่าง')

    async def test_new_proposal_replaces_old_draft(self):
        old = await self.make_draft('เก่า')
        await self.make_draft('ใหม่')
        closed = [m for m in of_type(self.alice, 'agent_proposal_closed') if m['proposal_id'] == old['proposal_id']]
        self.assertEqual([m['status'] for m in closed], ['superseded'])
        await server.handle_agent_decide(self.alice, 'alice', {'proposal_id': old['proposal_id'], 'decision': 'approve'})
        self.assertEqual(self.group_senders(), [])

    def test_should_wake(self):
        self.assertTrue(should_wake('alice', 'private', 'สวัสดี'))
        self.assertTrue(should_wake('Alice', 'group', 'hi ALICE'))
        self.assertTrue(should_wake('alice', 'group', 'พรุ่งนี้ประชุมไหม'))
        self.assertTrue(should_wake('alice', 'group', 'ready?'))
        self.assertFalse(should_wake('alice', 'group', 'ทานข้าวแล้ว'))
