#!/usr/bin/env python3
"""Ask before recognizable MCP messages and mentions; defer other MCP calls."""
import json
import re
import sys


# A user-facing mention must start at a token boundary. Email addresses alone
# do not count. Structured and platform-specific mention forms are also checked.
MENTION = re.compile(r'(?i)(?<![\w.+-])@[\w\u4e00-\u9fff-]+|<@[^>]+>|<at(?:\s|>)|\[at:[^\]]+\]')
WRITES = re.compile(r'(?i)(?:^|[_./+ -])(send|create|post|reply|update|edit|add|publish|notify|forward)(?:$|[_./+ -])')
READS = re.compile(r'(?i)(?:^|[_./+ -])(get|list|search|query|fetch|lookup|read|describe)(?:$|[_./+ -])')
MESSAGE = re.compile(r'(?i)(?:message|messages|chat|im[_./-]v\d|im[_./-]message)')


def strings_and_mentions(value, depth=0):
    if depth > 20:
        return [], False
    strings = []
    mention = False
    if isinstance(value, dict):
        marker = str(value.get('type', value.get('tag', ''))).lower()
        mention = marker in {'mention', 'at', 'user_mention'}
        for key, child in value.items():
            if str(key).lower() in {'mentions', 'mentioned_users', 'mentionedusers',
                                    'at_users', 'at_list', 'mention_ids', 'notify_user_ids'} and child:
                mention = True
            extra, detected = strings_and_mentions(child, depth + 1)
            strings.extend(extra)
            mention |= detected
    elif isinstance(value, list):
        for child in value:
            extra, detected = strings_and_mentions(child, depth + 1)
            strings.extend(extra)
            mention |= detected
    elif isinstance(value, str):
        strings.append(value)
        mention = bool(MENTION.search(value))
        # Many MCP APIs wrap message bodies as JSON strings.
        if len(value) <= 100000 and value.lstrip().startswith(('{', '[')):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                extra, detected = strings_and_mentions(parsed, depth + 1)
                strings.extend(extra)
                mention |= detected
    return strings, mention


def action_values(value, depth=0):
    if depth > 20:
        return []
    result = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {'action', 'method', 'operation', 'op', 'resource',
                                   'path', 'url', 'api', 'tool', 'tool_name', 'endpoint'} and isinstance(child, str):
                result.append(child[:512])
            result.extend(action_values(child, depth + 1))
    elif isinstance(value, list):
        for child in value:
            result.extend(action_values(child, depth + 1))
    return result


def decision(tool, tool_input):
    if not isinstance(tool, str) or not tool.startswith('mcp__'):
        return None
    normalized = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', tool).lower()
    _, mention = strings_and_mentions(tool_input)
    # Tool names are authoritative signals; request method/path/action values
    # supplement generic API-wrapper names without inspecting private state.
    actions = ' '.join(action_values(tool_input))
    write = bool(WRITES.search(normalized) or WRITES.search(actions)
                 or re.search(r'(?i)\b(?:POST|PUT|PATCH)\b', actions))
    read = bool(READS.search(normalized))
    message = bool(MESSAGE.search(normalized) or MESSAGE.search(actions))
    lark = bool(re.search(r'(?i)(?:lark|feishu)', normalized))
    if ((write or not read) and re.search(
            r'(?i)(?:^|[_./+ -])(?:mention|notify|at)[_./+ -]+(?:user|users|person|people)(?:$|[_./+ -])',
            normalized + ' ' + actions)):
        return 'ask'
    if (message and write) or (lark and re.search(r'(?i)(?:^|[_./+ -])(send|forward)(?:$|[_./+ -])', normalized)):
        return 'ask'
    if mention and (write or not read):
        return 'ask'
    return None


def main():
    try:
        event = json.load(sys.stdin)
        result = decision(event.get('tool_name'), event.get('tool_input', {}))
    except (ValueError, TypeError, AttributeError, RecursionError):
        result = 'ask'
    if result:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse', 'permissionDecision': result,
            'permissionDecisionReason': 'This MCP operation may send a message or mention someone; please confirm.'
        }}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
