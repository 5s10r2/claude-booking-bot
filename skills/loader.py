"""
Skill file loader with in-memory caching, hot-reload, and YAML frontmatter parsing.

Each skill is a .md file with:
- YAML frontmatter (skill name, tools, description)
- XML-structured body (<instructions>, <example> tags)

Caching: Files are cached in memory for RELOAD_INTERVAL seconds.
Edit a .md file → next API call picks up changes. No server restart needed.
"""

import re
import time
from pathlib import Path
from typing import Any

import yaml

from core.log import get_logger

log = get_logger(__name__)

SKILLS_DIR = Path(__file__).parent

# path → (last_check_time, parsed_data)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

# How often to check file staleness (seconds).
# During this window, the cached version is returned without hitting disk.
RELOAD_INTERVAL = 30


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_skill_file(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter + body from a skill .md file.

    Returns {"meta": dict, "content": str}.
    """
    meta: dict[str, Any] = {}
    body = text

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if fm_match:
        try:
            meta = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError as exc:
            log.warning("YAML parse error in skill file: %s", exc)
            meta = {}
        body = fm_match.group(2)

    return {"meta": meta, "content": body.strip()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_skill(agent: str, skill_name: str) -> dict[str, Any]:
    """Load a single skill .md file with hot-reload caching.

    Returns {"meta": dict, "content": str}.
    Raises FileNotFoundError if the skill file does not exist.
    """
    path = SKILLS_DIR / agent / f"{skill_name}.md"
    path_key = str(path)
    now = time.time()

    cached = _cache.get(path_key)
    if cached and (now - cached[0]) < RELOAD_INTERVAL:
        return cached[1]

    # Read and parse (or re-read if stale)
    content = path.read_text(encoding="utf-8")
    parsed = _parse_skill_file(content)
    _cache[path_key] = (now, parsed)
    return parsed


def get_skill_meta(agent: str, skill_name: str) -> dict[str, Any]:
    """Level 1: Load only metadata (name, tools, description). Cheap."""
    return load_skill(agent, skill_name)["meta"]


def build_skill_prompt(
    agent: str,
    skills: list[str],
    **template_vars: Any,
) -> tuple[str, str]:
    """Build a two-block system prompt from skill files.

    Returns (base_prompt, skill_prompt):
        base_prompt  — Always cached (identity + format + rules). ~3,500+ chars.
        skill_prompt — Dynamic per turn (instructions + examples for 2-4 skills). NOT cached.

    Template variables (e.g. {brand_name}, {language_directive}) are injected
    using the existing ``format_prompt`` from ``core.prompts``.
    """
    from core.prompts import format_prompt  # local import to avoid circular dependency

    # Base prompt — always loaded
    base_data = load_skill(agent, "_base")
    base = format_prompt(base_data["content"], **template_vars)

    # Dynamic skill sections
    skill_sections: list[str] = []
    for skill_name in skills:
        try:
            data = load_skill(agent, skill_name)
            skill_sections.append(data["content"])
        except FileNotFoundError:
            log.warning("Skill file not found: %s/%s.md — skipping", agent, skill_name)

    skill_prompt = format_prompt("\n\n".join(skill_sections), **template_vars)

    return base, skill_prompt


def clear_cache() -> None:
    """Clear the in-memory cache. Useful for testing."""
    _cache.clear()
