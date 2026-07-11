"""
Pathfinder service: find career paths between two professions.

Uses networkx directed graph built from profession exits (salidas).

Characteristic accumulation rules (per WFRP2):
  - Primary characteristics (%):   MAX across all professions in path (step of 5 %)
  - Secondary characteristics:     MAX across all professions in path (step of 1 unit)
  Both sets use the highest value any single profession in the path offers.
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
    Return up to max_paths simple paths from start to end, shortest first.
    Each path is a list of profession IDs (including start and end).

    Uses nx.shortest_simple_paths (Yen's algorithm) instead of
    all_simple_paths: the latter enumerates EVERY simple path up to `cutoff`
    hops before sorting, which is exponential in dense graphs - with ~230
    professions and ~1800 exit edges it can hang for minutes. Yen's algorithm
    yields paths lazily in increasing-length order, so itertools.islice can
    stop after max_paths without ever exploring the rest. `cutoff` still caps
    how long a path is allowed to be, applied as a post-filter.
    """
    if not NX_AVAILABLE or G is None:
        return []
    if start_id not in G or end_id not in G:
        return []
    try:
        found = []
        for path in nx.shortest_simple_paths(G, source=start_id, target=end_id):
            if len(path) - 1 > cutoff:
                break
            found.append(path)
            if len(found) >= max_paths:
                break
        return found
    except nx.NetworkXNoPath:
        return []
    except Exception as e:
        logger.error(f"Pathfinder error: {e}")
        return []


def _multi_source_shortest_path(G, sources: set, target: int) -> Optional[tuple]:
    """
    BFS from several source nodes at once. Returns (path, source_used) where
    path is the node list from source_used to target (inclusive), or None if
    target isn't reachable from any source. When several sources could reach
    target, BFS naturally returns the overall-shortest sub-path.
    """
    from collections import deque

    if target in sources:
        return [target], target

    visited = set(sources)
    parent = {}
    queue = deque(sources)
    while queue:
        node = queue.popleft()
        if node not in G:
            continue
        for nxt in G.successors(node):
            if nxt in visited:
                continue
            visited.add(nxt)
            parent[nxt] = node
            if nxt == target:
                path = [nxt]
                cur = nxt
                while cur not in sources:
                    cur = parent[cur]
                    path.append(cur)
                path.reverse()
                return path, path[0]
            queue.append(nxt)
    return None


def find_path_with_waypoints(G, stops: list) -> Optional[dict]:
    """
    Find a single route through an ordered list of required stops:
    stops = [start_id, waypoint1_id, ..., waypoint_n_id, end_id].

    Unlike chaining independent start->end lookups, each leg is searched with
    ALL professions visited so far as valid jump-off points, not just the
    immediately previous stop - once a career has been part of the route,
    its exits stay usable for reaching the next stop (mirrors how a
    character's full career history, not just their current career, opens up
    later options).

    Returns {'path_ids': [...], 'branch_points': {idx: source_id}} where
    branch_points marks, by index into path_ids, any leg that continued from
    an earlier stop rather than from the immediately preceding profession in
    the displayed list - or None if no route satisfies all the stops.
    """
    if not NX_AVAILABLE or G is None or len(stops) < 2:
        return None
    for sid in stops:
        if sid not in G:
            return None

    full_path = [stops[0]]
    visited_set = {stops[0]}
    branch_points = {}

    for target in stops[1:]:
        if target in visited_set:
            continue
        result = _multi_source_shortest_path(G, visited_set, target)
        if result is None:
            return None
        sub_path, source_used = result
        new_nodes = sub_path[1:]
        if source_used != full_path[-1]:
            branch_points[len(full_path)] = source_used
        full_path.extend(new_nodes)
        visited_set.update(new_nodes)

    return {'path_ids': full_path, 'branch_points': branch_points}


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
            'skills_by_group': {group_key: [ProfessionSkill, ...]},
            'talents_by_group': {group_key: [ProfessionTalent, ...]},
            'trappings': [ProfessionTrapping, ...],
          },
          ...
        ],
        'totals': {
          'primary': {field: int},
          'secondary': {field: int},
        },
        'all_skills': {group_label: [ProfessionSkill, ...]},  # deduplicated across path
        'all_talents': {group_label: [ProfessionTalent, ...]},
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
            totals_secondary[f] = max(totals_secondary[f], val)

        # Skills by group (get_skills_by_group now returns ProfessionSkill objects)
        skills_by_group = prof.get_skills_by_group()
        for group_key, ps_list in skills_by_group.items():
            if group_key is None:
                for ps in ps_list:
                    uid = (ps.skill.id, ps.specialization)
                    if uid not in all_skill_ids:
                        all_skill_ids.add(uid)
                        label = f'm_{ps.skill.id}_{ps.specialization or ""}'
                        all_skill_groups[label] = [ps]
            else:
                new_ps = [ps for ps in ps_list
                          if (ps.skill.id, ps.specialization) not in all_skill_ids]
                if new_ps:
                    global_skill_group_counter += 1
                    label = f'g_{global_skill_group_counter}'
                    all_skill_groups[label] = ps_list
                    for ps in new_ps:
                        all_skill_ids.add((ps.skill.id, ps.specialization))

        # Talents by group (same change)
        talents_by_group = prof.get_talents_by_group()
        for group_key, pt_list in talents_by_group.items():
            if group_key is None:
                for pt in pt_list:
                    uid = (pt.talent.id, pt.specialization)
                    if uid not in all_talent_ids:
                        all_talent_ids.add(uid)
                        label = f'm_{pt.talent.id}_{pt.specialization or ""}'
                        all_talent_groups[label] = [pt]
            else:
                new_pt = [pt for pt in pt_list
                          if (pt.talent.id, pt.specialization) not in all_talent_ids]
                if new_pt:
                    global_talent_group_counter += 1
                    label = f'g_{global_talent_group_counter}'
                    all_talent_groups[label] = pt_list
                    for pt in new_pt:
                        all_talent_ids.add((pt.talent.id, pt.specialization))

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
