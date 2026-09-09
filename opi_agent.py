#!/usr/bin/env python3
"""opi-agent: Agent runtime for Orange Pi single-board computers.

This is the main entry point that delegates to the modular CLI.
"""

from opi_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
