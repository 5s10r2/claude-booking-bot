"""
Dynamic skill loading system for the Claude Booking Bot.

Skills are .md files with YAML frontmatter + XML-structured content.
Each skill contains instructions and few-shot examples that are loaded
dynamically per turn based on user intent.

Architecture:
    loader.py    — File loading, YAML parsing, caching, hot-reload
    skill_map.py — Skill → tool mapping, keyword fallback detection
    broker/      — Skill files for the broker agent
"""
