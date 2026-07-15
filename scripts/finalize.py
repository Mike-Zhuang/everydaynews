#!/usr/bin/env python3
from daily_frontier_intelligence.cli import main

raise SystemExit(main(["finalize", *__import__("sys").argv[1:]]))
