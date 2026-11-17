#!/usr/bin/env python3
"""Preserve existing MCP hook registrations while deferring to Claude permissions."""
import sys


def main():
    # Consume the event without returning a permission decision. Existing
    # registrations remain valid and Claude's own rules decide every MCP call.
    sys.stdin.read()
    return 0


if __name__ == '__main__':
    sys.exit(main())
