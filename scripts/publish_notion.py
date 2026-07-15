#!/usr/bin/env python3
from daily_frontier_intelligence.cli import main

raise SystemExit(main(["publish-notion", *__import__("sys").argv[1:]]))
