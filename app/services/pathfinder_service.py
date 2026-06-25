"""
Pathfinder service: find career paths between two professions.

Uses networkx directed graph built from profession exits (salidas).

Characteristic accumulation rules (per user spec):
  - Primary characteristics (%):  MAX across all professions in path
  - Secondary characteristics:    SUM across all professions in path
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    NX_AVAILABLE = True
except ImportError:
    NX_AVAILABLE = False
    logger.warning("networkx not available – pathfinder disabled.")


def build_graph(professions: list) -> 'nx.DiGraph':
    """Build a directed graph from profession exits."""
    if not NX_AVAILABLE:
        return None
    G = nx.DiGraph()
    for prof in professions:
        G.add_node(prof.id, name=prof.name)
        for exit_prof in prof.exits:
            G.add_edge(prof.id, exit_prof.id)
    return G


def find_paths(G, start_id: int, end_id: int, max_paths: int = 5, cutoff: int = 10) -> list:
    """
    Return up to max_paths simple paths from start to end, sorted by length.
    Each path is a list of profession IDs (including start and end).
    """
    if not NX_AVAILABLE or G is None:
        return []
    if start_id not in G or end_id not in G:
        return []
    try:
        paths = list(nx.all_simple_paths(G, source=start_id, target=end_id, cutoff=cutoff))
        paths.sort(key=len)
        return paths[:max_paths]
    except nx.NetworkXNoPath:
        return []
    except Exception as e:
        logger.error(f"Pathfinder error: {e}")
        return []


def compute_path_stats(path_ids: list, profession_map: dict) -> dict:
    """
    Compute accumulated stats for a path of profession IDs.

    Returns:
      {
        'steps': [
          {
            'profession': Profession,
            'primary': {field: value_or_None},
            'secondary': {field: value_or_None},
            'skills_by_group': {group_key: [Skill, ...]},
            'talents_by_group': {group_key: [Talent, ...]},
            'trappings': [ProfessionTrapping, ...],
          },
          ...
        ],
        'totals': {
          'primary': {field: int},
          'secondary': {field: int},
        },
        'all_skills': {group_label: [Skill, ...]},  # deduplicated across path
        'all_talents': {group_label: [Talent, ...]},
        'all_trappings': [ProfessionTrapping, ...],
      }
    """
    from app.models.profession import Profession

    primary_fields = Profession.PRIMARY_FIELDS
    secondary_fields = Profession.SECONDARY_FIELDS

    totals_primary = {f: 0 for f in primary_fields}
    totals_secondary = {f: 0 for f in secondary_fields}

    steps = []
    all_skill_ids = set()
    all_talent_ids = set()
    all_trappings = []
    seen_trapping_names = set()

    # Counters for labelling OR groups across the whole path
    global_skill_group_counter = 0
    global_talent_group_counter = 0
    all_skill_groups = {}
    all_talent_groups = {}

    for prof_id in path_ids:
        prof = profession_map.get(prof_id)
        if prof is None:
            continue

        step_primary = {}
        step_secondary = {}

        for f in primary_fields:
            val = getattr(prof, f) or 0
            step_primary[f] = val
            totals_primary[f] = max(totals_primary[f], val)

        for f in secondary_fields:
            val = getattr(prof, f) or 0
            step_secondary[f] = val
            totals_secondary[f] += val

        # Skills by group
        skills_by_group = prof.get_skills_by_group()
        for group_key, skill_list in skills_by_group.items():
            if group_key is None:
                # Mandatory – each skill as its own group
                for sk in skill_list:
                    if sk.id not in all_skill_ids:
                        all_skill_ids.add(sk.id)
                        label = f'm_{sk.id}'
                        all_skill_groups[label] = [sk]
            else:
                # OR-choice group
                new_skills = [sk for sk in skill_list if sk.id not in all_skill_ids]
                if new_skills:
                    global_skill_group_counter += 1
                    label = f'g_{global_skill_group_counter}'
                    all_skill_groups[label] = skill_list
                    for sk in new_skills:
                        all_skill_ids.add(sk.id)

        # Talents by group
        talents_by_group = prof.get_talents_by_group()
        for group_key, talent_list in talents_by_group.items():
            if group_key is None:
                for tl in talent_list:
                    if tl.id not in all_talent_ids:
                        all_talent_ids.add(tl.id)
                        label = f'm_{tl.id}'
                        all_talent_groups[label] = [tl]
            else:
                new_talents = [tl for tl in talent_list if tl.id not in all_talent_ids]
                if new_talents:
                    global_talent_group_counter += 1
                    label = f'g_{global_talent_group_counter}'
                    all_talent_groups[label] = talent_list
                    for tl in new_talents:
                        all_talent_ids.add(tl.id)

        # Trappings (deduplicate by name)
        step_trappings = []
        for trp in prof.trappings:
            step_trappings.append(trp)
            if trp.name.lower() not in seen_trapping_names:
                seen_trapping_names.add(trp.name.lower())
                all_trappings.append(trp)

        steps.append({
            'profession': prof,
            'primary': step_primary,
            'secondary': step_secondary,
            'skills_by_group': skills_by_group,
            'talents_by_group': talents_by_group,
            'trappings': step_trappings,
        })

    return {
        'steps': steps,
        'totals': {
            'primary': totals_primary,
            'secondary': totals_secondary,
        },
        'all_skills': all_skill_groups,
        'all_talents': all_talent_groups,
        'all_trappings': all_trappings,
    }
