"""Tests for the career pathfinder: graph building, path search, and the
accumulated-stats computation (max-across-path rule for characteristics,
deduplication of skills/talents/trappings across the path)."""
from app.services.pathfinder_service import build_graph, find_paths, compute_path_stats
from app.models.profession import ProfessionSkill, ProfessionTalent, ProfessionTrapping


def _link_exit(db, source, target):
    source.exits.append(target)
    db.session.commit()


# ── build_graph / find_paths ─────────────────────────────────────────────────

def test_find_paths_direct_exit(db, make_profession):
    a = make_profession(name='A')
    b = make_profession(name='B')
    a.exits.append(b)
    db.session.commit()

    professions = [a, b]
    G = build_graph(professions)
    paths = find_paths(G, a.id, b.id)
    assert paths == [[a.id, b.id]]


def test_find_paths_multi_hop(db, make_profession):
    a = make_profession(name='A')
    b = make_profession(name='B')
    c = make_profession(name='C')
    a.exits.append(b)
    b.exits.append(c)
    db.session.commit()

    professions = [a, b, c]
    G = build_graph(professions)
    paths = find_paths(G, a.id, c.id)
    assert paths == [[a.id, b.id, c.id]]


def test_find_paths_returns_shortest_first(db, make_profession):
    a = make_profession(name='A')
    b = make_profession(name='B')
    c = make_profession(name='C')
    # Direct A->C plus a longer A->B->C
    a.exits.append(c)
    a.exits.append(b)
    b.exits.append(c)
    db.session.commit()

    professions = [a, b, c]
    G = build_graph(professions)
    paths = find_paths(G, a.id, c.id)
    assert paths[0] == [a.id, c.id]
    assert [a.id, b.id, c.id] in paths


def test_find_paths_no_path_returns_empty(db, make_profession):
    a = make_profession(name='A')
    b = make_profession(name='B')
    professions = [a, b]  # no exits linking them
    G = build_graph(professions)
    assert find_paths(G, a.id, b.id) == []


def test_find_paths_unknown_ids_returns_empty(db, make_profession):
    a = make_profession(name='A')
    G = build_graph([a])
    assert find_paths(G, a.id, 999999) == []
    assert find_paths(G, 999999, a.id) == []


def test_find_paths_respects_max_paths(db, make_profession):
    a = make_profession(name='A')
    b = make_profession(name='B')
    c = make_profession(name='C')
    d = make_profession(name='D')
    e = make_profession(name='E')
    # Multiple distinct paths from A to E
    a.exits.extend([b, c])
    b.exits.append(e)
    c.exits.append(d)
    d.exits.append(e)
    db.session.commit()

    professions = [a, b, c, d, e]
    G = build_graph(professions)
    paths = find_paths(G, a.id, e.id, max_paths=1)
    assert len(paths) == 1


# ── compute_path_stats ────────────────────────────────────────────────────────

def test_compute_path_stats_takes_max_of_primary_and_secondary(db, make_profession):
    a = make_profession(name='A', ws=5, movement=1)
    b = make_profession(name='B', ws=10, movement=0)
    prof_map = {a.id: a, b.id: b}

    stats = compute_path_stats([a.id, b.id], prof_map)
    assert stats['totals']['primary']['ws'] == 10
    assert stats['totals']['secondary']['movement'] == 1


def test_compute_path_stats_treats_missing_characteristic_as_zero(db, make_profession):
    a = make_profession(name='A', ws=None)
    prof_map = {a.id: a}
    stats = compute_path_stats([a.id], prof_map)
    assert stats['totals']['primary']['ws'] == 0


def test_compute_path_stats_deduplicates_mandatory_skills_across_path(db, make_profession, make_skill):
    skill = make_skill(name_es='Percepción')
    a = make_profession(name='A')
    b = make_profession(name='B')
    db.session.add(ProfessionSkill(profession_id=a.id, skill_id=skill.id))
    db.session.add(ProfessionSkill(profession_id=b.id, skill_id=skill.id))
    db.session.commit()
    db.session.refresh(a)
    db.session.refresh(b)

    prof_map = {a.id: a, b.id: b}
    stats = compute_path_stats([a.id, b.id], prof_map)
    # Same skill+specialization appearing in both professions counts once.
    total_skill_entries = sum(len(v) for v in stats['all_skills'].values())
    assert total_skill_entries == 1


def test_compute_path_stats_deduplicates_trappings_by_name(db, make_profession):
    a = make_profession(name='A')
    b = make_profession(name='B')
    db.session.add(ProfessionTrapping(profession_id=a.id, name='Daga'))
    db.session.add(ProfessionTrapping(profession_id=b.id, name='Daga'))
    db.session.commit()
    db.session.refresh(a)
    db.session.refresh(b)

    prof_map = {a.id: a, b.id: b}
    stats = compute_path_stats([a.id, b.id], prof_map)
    assert len(stats['all_trappings']) == 1


def test_compute_path_stats_keeps_choice_group_skills_separate_per_step(db, make_profession, make_skill):
    s1 = make_skill(name_es='Percepción')
    s2 = make_skill(name_es='Callejeo')
    a = make_profession(name='A')
    db.session.add(ProfessionSkill(profession_id=a.id, skill_id=s1.id, choice_group=1))
    db.session.add(ProfessionSkill(profession_id=a.id, skill_id=s2.id, choice_group=1))
    db.session.commit()
    db.session.refresh(a)

    stats = compute_path_stats([a.id], {a.id: a})
    group_labels = [k for k in stats['all_skills'] if k.startswith('g_')]
    assert len(group_labels) == 1
    assert len(stats['all_skills'][group_labels[0]]) == 2


def test_compute_path_stats_builds_steps_in_path_order(db, make_profession):
    a = make_profession(name='A')
    b = make_profession(name='B')
    stats = compute_path_stats([a.id, b.id], {a.id: a, b.id: b})
    assert [s['profession'].name for s in stats['steps']] == ['A', 'B']


# ── Route-level tests ────────────────────────────────────────────────────────

def test_pathfinder_index_is_public(client):
    resp = client.get('/buscador/')
    assert resp.status_code == 200


def test_pathfinder_rejects_same_start_and_end(client, make_profession):
    a = make_profession(name='A')
    resp = client.post('/buscador/', data={'start_id': str(a.id), 'end_id': str(a.id)},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'deben ser distintas'.encode('utf-8') in resp.data


def test_pathfinder_finds_and_displays_path(db, client, make_profession):
    a = make_profession(name='Alborotador')
    b = make_profession(name='Veterano')
    a.exits.append(b)
    db.session.commit()

    resp = client.post('/buscador/', data={'start_id': str(a.id), 'end_id': str(b.id)},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'Alborotador'.encode('utf-8') in resp.data
    assert 'Veterano'.encode('utf-8') in resp.data


def test_pathfinder_reports_no_path_found(client, make_profession):
    a = make_profession(name='A')
    b = make_profession(name='B')
    resp = client.post('/buscador/', data={'start_id': str(a.id), 'end_id': str(b.id)},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'no se encontr'.encode('utf-8') in resp.data.lower()
