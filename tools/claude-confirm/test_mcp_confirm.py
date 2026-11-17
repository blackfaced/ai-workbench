import json
from pathlib import Path
import subprocess
import sys
import unittest

HOOK = Path(__file__).with_name('mcp_confirm.py')


def decide(tool, payload):
    event = {'tool_name': tool, 'tool_input': payload, 'hook_event_name': 'PreToolUse'}
    result = subprocess.run([sys.executable, '-B', str(HOOK)], input=json.dumps(event),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'] if result.stdout else None


class McpConfirmTests(unittest.TestCase):
    def test_sending_messages_requests_confirmation(self):
        for tool, payload in [
            ('mcp__lark__send_message', {'text': 'hello'}),
            ('mcp__feishu__im_v1_message_create', {'content': '{"text":"hello"}'}),
            ('mcp__lark__im_v1_message_reply', {'text': 'hello'}),
            ('mcp__lark__call', {'method': 'POST', 'path': '/im/v1/messages', 'body': {'text': 'hello'}}),
            ('mcp__other__sendMessage', {'text': 'hello'}),
        ]:
            with self.subTest(tool=tool):
                self.assertEqual(decide(tool, payload), 'ask')

    def test_system_mentions_request_confirmation(self):
        for tool, payload in [
            ('mcp__tracker__create_comment', {'body': 'Please review @someone'}),
            ('mcp__tracker__update_issue', {'description': '<at user_id="u1">Person</at>'}),
            ('mcp__tracker__post_comment', {'body': '<@U123> please review'}),
            ('mcp__tracker__create_comment', {'body': json.dumps({'tag': 'at', 'user_id': 'u1'})}),
            ('mcp__tracker__create_comment', {'content': [{'type': 'mention', 'id': 'u1'}]}),
            ('mcp__tracker__call', {'method': 'POST', 'path': '/comments', 'body': {'mentions': ['u1']}}),
            ('mcp__tracker__mention_user', {'user_id': 'u1'}),
            ('mcp__tracker__update_issue', {'notify_user_ids': ['u1']}),
        ]:
            with self.subTest(tool=tool):
                self.assertEqual(decide(tool, payload), 'ask')

    def test_other_calls_keep_normal_permissions(self):
        for tool, payload in [
            ('mcp__lark__im_v1_message_get', {'message_id': 'm1'}),
            ('mcp__lark__search_messages', {'query': 'send message to @someone'}),
            ('mcp__tracker__search', {'query': '@someone'}),
            ('mcp__tracker__create_issue', {'description': 'Contact person@example.com'}),
            ('mcp__tracker__create_comment', {'body': 'ordinary update'}),
            ('mcp__memory__search_graph', {'query': 'example'}),
            ('Bash', {'command': 'echo hello'}),
        ]:
            with self.subTest(tool=tool):
                self.assertIsNone(decide(tool, payload))

    def test_malformed_event_asks(self):
        result = subprocess.run([sys.executable, '-B', str(HOOK)], input='{', text=True,
                                capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'], 'ask')


if __name__ == '__main__':
    unittest.main()
