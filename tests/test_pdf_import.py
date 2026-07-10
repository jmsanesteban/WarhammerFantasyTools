"""Tests for the PDF import pipeline - the most fragile area of the app,
with several previously-shipped real bugs:
  1. skills/talents chips confirmed in the review UI were silently discarded
     and replaced by stale English source text on save.
  2. the review-session job/cache lived under tempfile.gettempdir(), so it
     was wiped on every container redeploy.
  3. exits/entries (career links) were always dumped as unlinked text instead
     of being auto-linked when a confident match existed.
  4. a badly-OCR'd/translated "Trappings" header caused the whole enseres
     block to be swallowed into talents_raw instead of its own section.
  5. the ES synonym dictionary (GTranslate output vs. official WFRP2 name)
     was only applied to skill/talent names and profession names, never to
     the OTHER career names listed in exits/entries.
This file exercises the fixed behavior directly, plus the underlying file-
based job/cache persistence and the save-time duplicate guard.
"""
import os
import time

import pytest

from app.routes import admin as admin_routes
from app.services.pdf_processor import _parse_sections
from app.models.profession import Profession, ProfessionSkill, ProfessionTalent


@pytest.fixture(autouse=True)
def _clean_pdf_cache_dirs():
    """The job/cache stores are plain JSON files on disk, not part of the
    per-test DB transaction - clear them so tests don't see each other's state."""
    yield
    for d in (admin_routes._JOBS_DIR, admin_routes._CACHE_DIR):
        for fname in os.listdir(d):
            try:
                os.remove(os.path.join(d, fname))
            except OSError:
                pass


def _grant_admin_pdf_perm(db, user):
    from app.models.permission import Permission
    user.direct_permissions.append(db.session.get(Permission, 'professions.import'))
    db.session.commit()


# ── _match_and_save_skills / _match_and_save_talents ────────────────────────
# The critical regression: matching must always use the ES/chip-confirmed
# text (skills_raw/talents_raw), never the stale original English text
# (skills_raw_en/talents_raw_en), even when both are present.

def test_match_and_save_skills_uses_es_not_stale_english(app, db, make_profession, make_skill):
    correct = make_skill(name_es='Percepción')
    make_skill(name_es='Callejeo')  # would be matched if the EN field were used by mistake

    prof = make_profession(name='Explorador')
    with app.test_request_context():
        admin_routes._match_and_save_skills(
            prof,
            skills_raw='Percepción',          # what the admin confirmed in the review UI
            skills_raw_en='Street Wise',       # stale original PDF text - must be ignored
        )
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    assert {ps.skill_id for ps in saved} == {correct.id}


def test_match_and_save_talents_uses_es_not_stale_english(app, db, make_profession, make_talent):
    correct = make_talent(name_es='Ambidiestro')
    make_talent(name_es='Callejero')

    prof = make_profession(name='Explorador')
    with app.test_request_context():
        admin_routes._match_and_save_talents(
            prof, talents_raw='Ambidiestro', talents_raw_en='Streetwise',
        )
    db.session.commit()

    saved = ProfessionTalent.query.filter_by(profession_id=prof.id).all()
    assert {pt.talent_id for pt in saved} == {correct.id}


def test_match_and_save_skills_extracts_specialization(app, db, make_profession, make_skill):
    skill = make_skill(name_es='Oficio')
    prof = make_profession(name='Artesano')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Oficio (Herrero)')
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).first()
    assert saved.skill_id == skill.id
    assert saved.specialization == 'Herrero'


def test_match_and_save_skills_ignores_unmatched_text(app, db, make_profession, make_skill):
    make_skill(name_es='Percepción')
    prof = make_profession(name='Explorador')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Habilidad Totalmente Inventada')
    db.session.commit()

    assert ProfessionSkill.query.filter_by(profession_id=prof.id).count() == 0


def test_match_and_save_skills_deduplicates_same_skill_and_spec(app, db, make_profession, make_skill):
    skill = make_skill(name_es='Oficio')
    prof = make_profession(name='Artesano')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Oficio (Herrero), Oficio (Herrero)')
    db.session.commit()

    assert ProfessionSkill.query.filter_by(profession_id=prof.id).count() == 1


def test_match_and_save_skills_groups_o_alternatives_under_shared_choice_group(
    app, db, make_profession, make_skill,
):
    """'A o B' means 'pick exactly one of these two' - both sides must share a
    choice_group so the profession editor renders them as a single group instead
    of two independent, always-granted skills."""
    a = make_skill(name_es='Percepción')
    b = make_skill(name_es='Callejeo')
    prof = make_profession(name='Explorador')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Percepción o Callejeo')
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    groups = {ps.choice_group for ps in saved}
    assert None not in groups
    assert len(groups) == 1
    assert {ps.skill_id for ps in saved} == {a.id, b.id}


def test_match_and_save_skills_splits_specializations_own_alternative_list_into_grouped_rows(
    app, db, make_profession, make_skill,
):
    """'Hablar idioma (Bretón o Tileano)' is ONE skill with a multi-choice
    specialization, not two alternative skills - but the profession edit form
    models each named specialization choice as its own ProfessionSkill row
    ('Mismo Gr. = el jugador elige uno'), so it must be saved as two rows
    (Bretón / Tileano) sharing one choice_group, not a single row holding the
    literal 'Bretón o Tileano' string, and not split into a broken
    'Hablar idioma (Bretón' + an unmatched 'Tileano)' either."""
    skill = make_skill(name_es='HABLAR IDIOMA (Varios)')
    prof = make_profession(name='Alborotador')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Hablar idioma (Bretón o Tileano)')
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    assert len(saved) == 2
    assert all(ps.skill_id == skill.id for ps in saved)
    assert {ps.specialization for ps in saved} == {'Bretón', 'Tileano'}
    groups = {ps.choice_group for ps in saved}
    assert None not in groups
    assert len(groups) == 1


def test_match_and_save_skills_splits_specializations_own_comma_list_into_grouped_rows(
    app, db, make_profession, make_skill,
):
    """Same as above but with a 3-way comma+'o' list, matching the real
    'Hablar idioma (Bretón, Reikspiel o Tileano)' pattern from the book."""
    skill = make_skill(name_es='HABLAR IDIOMA (Varios)')
    prof = make_profession(name='Barbero cirujano')
    with app.test_request_context():
        admin_routes._match_and_save_skills(
            prof, skills_raw='Hablar idioma (Bretón, Reikspiel o Tileano)',
        )
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    assert len(saved) == 3
    assert {ps.specialization for ps in saved} == {'Bretón', 'Reikspiel', 'Tileano'}
    groups = {ps.choice_group for ps in saved}
    assert None not in groups
    assert len(groups) == 1


def test_match_and_save_skills_keeps_specialization_count_phrasing_as_single_row(
    app, db, make_profession, make_skill,
):
    """A free-form choice-count descriptor ('dos cualesquiera') names no
    specific values, so there is nothing to split - it must stay one row."""
    skill = make_skill(name_es='Actuar (Varios)')
    prof = make_profession(name='Artista')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Actuar (dos cualesquiera)')
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    assert len(saved) == 1
    assert saved[0].specialization == 'dos cualesquiera'
    assert saved[0].choice_group is None


def test_match_and_save_skills_treats_u_as_an_alternative_connector(
    app, db, make_profession, make_skill,
):
    """Spanish grammar swaps 'o' for 'u' before an o-/ho- sound (e.g. 'Carisma
    animal u Oficio'); it must be recognized as the same alternative-group marker."""
    a = make_skill(name_es='Carisma animal')
    b = make_skill(name_es='Oficio')
    prof = make_profession(name='Hechicero vulgar')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Carisma animal u Oficio (Boticario)')
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    groups = {ps.choice_group for ps in saved}
    assert None not in groups
    assert len(groups) == 1
    assert {ps.skill_id for ps in saved} == {a.id, b.id}


def test_match_and_save_skills_plain_comma_list_has_no_choice_group(
    app, db, make_profession, make_skill,
):
    """Plain comma-separated skills (no 'o'/'u' alternative) are all mandatory -
    none of them should be assigned to a choice_group."""
    make_skill(name_es='Percepción')
    make_skill(name_es='Callejeo')
    prof = make_profession(name='Explorador')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Percepción, Callejeo')
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    assert all(ps.choice_group is None for ps in saved)


def test_match_and_save_talents_groups_o_alternatives_under_shared_choice_group(
    app, db, make_profession, make_talent,
):
    a = make_talent(name_es='Ambidiestro')
    b = make_talent(name_es='Desarmar')
    prof = make_profession(name='Duelista')
    with app.test_request_context():
        admin_routes._match_and_save_talents(prof, talents_raw='Ambidiestro o Desarmar')
    db.session.commit()

    saved = ProfessionTalent.query.filter_by(profession_id=prof.id).all()
    groups = {pt.choice_group for pt in saved}
    assert None not in groups
    assert len(groups) == 1
    assert {pt.talent_id for pt in saved} == {a.id, b.id}


# ── _fuzzy_link_professions (exits/entries auto-linking) ────────────────────

def test_fuzzy_link_professions_matches_exact_name(app, db, make_profession):
    target = make_profession(name='Veterano')
    with app.test_request_context():
        matched, unmatched = admin_routes._fuzzy_link_professions('Veterano')
    assert matched == [target]
    assert unmatched == []


def test_fuzzy_link_professions_matches_close_name(app, db, make_profession):
    target = make_profession(name='Veterano')
    with app.test_request_context():
        # Minor OCR/translation variant - one character off.
        matched, unmatched = admin_routes._fuzzy_link_professions('Veternao', cutoff=0.8)
    assert matched == [target]
    assert unmatched == []


def test_fuzzy_link_professions_leaves_unmatched_names_pending(app, db, make_profession):
    make_profession(name='Veterano')
    with app.test_request_context():
        matched, unmatched = admin_routes._fuzzy_link_professions('Profesión Que No Existe')
    assert matched == []
    assert unmatched == ['Profesión Que No Existe']


def test_fuzzy_link_professions_handles_multiple_comma_separated(app, db, make_profession):
    p1 = make_profession(name='Veterano')
    p2 = make_profession(name='Capitán')
    with app.test_request_context():
        matched, unmatched = admin_routes._fuzzy_link_professions('Veterano, Capitán, Inventado')
    assert set(matched) == {p1, p2}
    assert unmatched == ['Inventado']


def _seed_default_synonyms(db):
    from app.models.synonym import Synonym, DEFAULT_SYNONYMS
    for source, target, is_prefix, notes in DEFAULT_SYNONYMS:
        db.session.add(Synonym(source=source, target=target, is_prefix=is_prefix, notes=notes))
    db.session.commit()


def test_fuzzy_link_professions_resolves_synonym_before_matching(app, db, make_profession):
    """Regression test: GTranslate's literal translation of a career name
    ('Campeón') differs from the official WFRP2 Spanish name ('Héroe') -
    the synonym dictionary must be consulted before giving up on a match."""
    _seed_default_synonyms(db)
    target = make_profession(name='Héroe', type='advanced')
    with app.test_request_context():
        matched, unmatched = admin_routes._fuzzy_link_professions('Campeón')
    assert matched == [target]
    assert unmatched == []


# ── Enseres misclassified as Talentos (Trappings header not recognized) ────

def test_parse_sections_moves_quantity_items_from_talents_to_trappings():
    """Regression test: when OCR/translation garbles the 'Enseres:' header
    badly enough that it isn't recognized as its own section, its content
    used to be silently swallowed into talents_raw with no way to recover it
    in the confirmation step. Equipment-quantity items ('4 Cuchillos...')
    are now detected and moved back into trappings_raw."""
    text = (
        'Talentos: Desenvainado rápido, Parada veloz, Pelea callejera, '
        '4 Cuchillos Arrojadizos, Gancho De Agarre, 10 Metros De Cuerda, '
        '1 Dosis De Veneno (Cualquiera)\n'
        'Accesos: Duelista\n'
        'Salidas: Sargento'
    )
    sections = _parse_sections(text)
    assert sections['talents_raw'] == 'Desenvainado rápido, Parada veloz, Pelea callejera'
    assert sections['trappings_raw'] == (
        '4 Cuchillos Arrojadizos, Gancho De Agarre, 10 Metros De Cuerda, 1 Dosis De Veneno (Cualquiera)'
    )


def test_parse_sections_leaves_talents_untouched_when_no_stray_trappings():
    text = 'Talentos: Desenvainado rápido, Parada veloz\nAccesos: Duelista\nSalidas: Sargento'
    sections = _parse_sections(text)
    assert sections['talents_raw'] == 'Desenvainado rápido, Parada veloz'
    assert sections['trappings_raw'] == ''


def test_parse_sections_appends_stray_items_after_a_real_trappings_section():
    text = (
        'Talentos: Certero, Astucia\n'
        'Enseres: Espada\n'
        'Accesos: Duelista'
    )
    sections = _parse_sections(text)
    # The real "Enseres:" header was recognized here, so nothing should move.
    assert sections['talents_raw'] == 'Certero, Astucia'
    assert sections['trappings_raw'] == 'Espada'


# ── Canonicalizing skill/talent chips to the exact catalog name ────────────
# A profession may only ever reference skills/talents already in the catalog
# (an "A o B" choice group is still built from two existing entries, never
# free text) - the review UI must show the real catalog name, not a near-miss
# like "preparar veneno" sitting next to the real "Preparar venenos".

def test_validate_pdf_professions_canonicalizes_near_miss_skill_name(db, make_skill):
    from app.models.skill import Skill
    make_skill(name_es='Preparar venenos')
    professions = [{'name': 'Asesino', 'type': 'advanced', 'skills_raw': 'preparar veneno'}]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['skills_raw'] == 'Preparar venenos'


def test_validate_pdf_professions_canonicalizes_near_miss_talent_name(db, make_talent):
    from app.models.talent import Talent
    make_talent(name_es='Especialista en armas')
    professions = [{'name': 'Asesino', 'type': 'advanced', 'talents_raw': 'especialistas en armas'}]

    result = admin_routes._validate_pdf_professions(professions, [], Talent.query.all())
    assert result[0]['talents_raw'] == 'Especialista en armas'


def test_validate_pdf_professions_keeps_specialization_suffix_when_canonicalizing(db, make_skill):
    from app.models.skill import Skill
    make_skill(name_es='Oficio')
    professions = [{'name': 'Artesano', 'type': 'basic', 'skills_raw': 'oficios (Herrero)'}]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['skills_raw'] == 'Oficio (Herrero)'


def test_validate_pdf_professions_canonicalizes_each_side_of_an_alternative(db, make_skill):
    from app.models.skill import Skill
    make_skill(name_es='Percepción')
    make_skill(name_es='Callejeo')
    professions = [{'name': 'Explorador', 'type': 'basic', 'skills_raw': 'percepcion o callejeos'}]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['skills_raw'] == 'Percepción o Callejeo'


def test_validate_pdf_professions_strips_varios_marker_before_specialization(db, make_skill):
    """Catalog skills that require a specialization store the marker literally in
    name_es (e.g. 'HABLAR IDIOMA (Varios)'). Appending the real specialization must
    replace that marker, not stack on top of it as 'HABLAR IDIOMA (Varios) (Reikspiel)'."""
    from app.models.skill import Skill
    make_skill(name_es='HABLAR IDIOMA (Varios)')
    professions = [{'name': 'Barquero', 'type': 'basic', 'skills_raw': 'Hablar idioma (Reikspiel)'}]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['skills_raw'] == 'HABLAR IDIOMA (Reikspiel)'


def test_validate_pdf_professions_keeps_specializations_own_alternative_list_intact(db, make_skill):
    """A skill's own specialization can list several alternative choices with
    'o'/commas INSIDE its parentheses (e.g. 'Hablar idioma (Bretón o Tileano)').
    That must not be mistaken for two different skill alternatives - the naive
    split used to cut right through the parenthesis, breaking it into
    'Hablar idioma (Bretón' and 'Tileano)' and mangling the catalog name into
    'HABLAR IDIOMA (Varios) o Tileano)'."""
    from app.models.skill import Skill
    make_skill(name_es='HABLAR IDIOMA (Varios)')
    professions = [{'name': 'Alborotador', 'type': 'basic', 'skills_raw': 'Hablar idioma (Bretón o Tileano)'}]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['skills_raw'] == 'HABLAR IDIOMA (Bretón o Tileano)'


def test_validate_pdf_professions_keeps_specializations_own_comma_list_intact(db, make_skill):
    """Same as above but with a comma-separated internal alternative list, which
    also used to be split as if each language were its own top-level skill item."""
    from app.models.skill import Skill
    make_skill(name_es='HABLAR IDIOMA (Varios)')
    professions = [{
        'name': 'Cochero', 'type': 'basic',
        'skills_raw': 'Hablar idioma (Bretón, Kisleviano o Tileano)',
    }]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['skills_raw'] == 'HABLAR IDIOMA (Bretón, Kisleviano o Tileano)'


def test_validate_pdf_professions_still_splits_genuine_top_level_alternative(db, make_skill):
    """Regression guard: fixing the internal-parenthesis case above must not
    break the ordinary 'A o B' case where each side really is a different skill."""
    from app.models.skill import Skill
    make_skill(name_es='SABIDURÍA ACADEMICA (Varios)')
    make_skill(name_es='Cotilleo')
    professions = [{
        'name': 'Alborotador', 'type': 'basic',
        'skills_raw': 'Sabiduría académica (Historia) o Cotilleo',
    }]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['skills_raw'] == 'SABIDURÍA ACADEMICA (Historia) o Cotilleo'


def test_validate_pdf_professions_leaves_genuinely_unmatched_skill_text_as_is(db, make_skill):
    from app.models.skill import Skill
    make_skill(name_es='Percepción')
    professions = [{'name': 'Explorador', 'type': 'basic', 'skills_raw': 'Habilidad Totalmente Inventada'}]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['skills_raw'] == 'Habilidad Totalmente Inventada'


def test_pdf_save_links_skill_by_canonical_name_shown_in_review(db, client, admin_user, login_as, make_skill):
    """End-to-end: the chip the admin sees and saves ('Preparar venenos', already
    canonicalized by the review page) must link to the real existing skill,
    never create a second near-duplicate entry."""
    skill = make_skill(name_es='Preparar venenos')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/pdf/guardar', data={
        'name': 'Asesino', 'type': 'advanced', 'skills_raw': 'Preparar venenos',
    }, follow_redirects=True)
    assert resp.status_code == 200

    from app.models.skill import Skill
    assert Skill.query.count() == 1
    prof = Profession.query.filter_by(name='Asesino').first()
    saved_ids = {ps.skill_id for ps in ProfessionSkill.query.filter_by(profession_id=prof.id).all()}
    assert saved_ids == {skill.id}


def test_normalize_career_list_corrects_gtranslate_name_mismatch(db):
    _seed_default_synonyms(db)
    from app.routes.admin import _normalize_career_list, _get_synonyms_dicts
    exact, prefix = _get_synonyms_dicts()
    result = _normalize_career_list('Duelista, Campeón, Espía', exact, prefix)
    assert result == 'Duelista, Héroe, Espía'


def test_normalize_career_list_does_not_touch_compound_names(db):
    """'Campeón judicial' is a distinct, legitimate career name - only the
    standalone 'Campeón' token should be corrected, not substrings of it."""
    _seed_default_synonyms(db)
    from app.routes.admin import _normalize_career_list, _get_synonyms_dicts
    exact, prefix = _get_synonyms_dicts()
    result = _normalize_career_list('Campeón judicial, Campeón', exact, prefix)
    assert result == 'Campeón judicial, Héroe'


def test_validate_pdf_professions_corrects_exits_and_entries(db):
    _seed_default_synonyms(db)
    professions = [{
        'name': 'Asesino', 'type': 'advanced',
        'exits_raw': 'Bribón, Campeón',
        'entries_raw': 'Campeón, Duelista',
    }]
    result = admin_routes._validate_pdf_professions(professions, [], [])
    assert result[0]['exits_raw']   == 'Bribón, Héroe'
    assert result[0]['entries_raw'] == 'Héroe, Duelista'


def test_pdf_save_links_exit_despite_gtranslate_name_mismatch(db, client, admin_user, login_as, make_profession):
    """End-to-end regression: a career exit written with GTranslate's literal
    (wrong) translation still links to the correct existing profession."""
    _seed_default_synonyms(db)
    target = make_profession(name='Héroe', type='advanced')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/pdf/guardar', data={
        'name': 'Asesino', 'type': 'advanced',
        'exits_raw': 'Campeón',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Asesino').first()
    assert target in prof.exits
    assert 'PENDIENTES' not in (prof.description or '')


# ── _validate_pdf_professions (duplicate triage + no_entries suppression) ──

def test_validate_pdf_professions_flags_exact_duplicate(db, make_profession):
    make_profession(name='Alborotador', type='basic')
    professions = [{'name': 'Alborotador', 'type': 'basic'}]

    result = admin_routes._validate_pdf_professions(professions, [], [])
    assert result[0]['dup_status'] == 'exact'
    assert result[0]['existing_prof']['name'] == 'Alborotador'


def test_validate_pdf_professions_flags_possible_duplicate(db, make_profession):
    make_profession(name='Alborotador', type='basic')
    professions = [{'name': 'Alborotadora', 'type': 'basic'}]  # 1-letter variant

    result = admin_routes._validate_pdf_professions(professions, [], [])
    assert result[0]['dup_status'] == 'possible'
    assert result[0]['existing_prof'] is None
    assert any(d['name'] == 'Alborotador' for d in result[0]['possible_duplicates'])


def test_validate_pdf_professions_flags_new_profession(db):
    professions = [{'name': 'Profesión Completamente Nueva', 'type': 'basic'}]
    result = admin_routes._validate_pdf_professions(professions, [], [])
    assert result[0]['dup_status'] == 'new'
    assert result[0]['possible_duplicates'] == []


def test_validate_pdf_professions_suppresses_no_entries_for_basic(db):
    professions = [{'name': 'Soldado Raso', 'type': 'basic', 'entries_raw': ''}]
    result = admin_routes._validate_pdf_professions(professions, [], [])
    assert result[0]['no_entries'] is False


def test_validate_pdf_professions_flags_no_entries_for_advanced(db):
    professions = [{'name': 'Capitán', 'type': 'advanced', 'entries_raw': ''}]
    result = admin_routes._validate_pdf_professions(professions, [], [])
    assert result[0]['no_entries'] is True


def test_validate_pdf_professions_flags_unmatched_skills(db, make_skill):
    from app.models.skill import Skill
    make_skill(name_es='Percepción')
    professions = [{'name': 'Nuevo', 'type': 'basic', 'skills_raw': 'Percepción, Habilidad Inventada'}]
    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert 'Habilidad Inventada' in result[0]['unmatched_skills']
    assert 'Percepción' not in result[0]['unmatched_skills']


# ── Specialization-count phrasing ("dos cualesquiera") must still match ─────
# A skill/talent needing a specialization can carry either a real specialization
# name (e.g. 'Hablar idioma (Reikspiel)') or the book's own free-form choice-count
# descriptor (e.g. 'Actuar (dos cualesquiera)'). The latter's text has little
# resemblance to the catalog's literal '(Varios)' marker, so a plain fuzzy-ratio
# comparison of the full/base strings falls short of the cutoff even though the
# base skill obviously exists - it must still match via the catalog's own debased
# (parenthetical-stripped) name.

def test_validate_pdf_professions_matches_specialization_count_phrasing(db, make_skill):
    from app.models.skill import Skill
    make_skill(name_es='Actuar (Varios)')
    professions = [{'name': 'Artista', 'type': 'basic', 'skills_raw': 'Actuar (dos cualesquiera)'}]

    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['unmatched_skills'] == []
    assert result[0]['skills_raw'] == 'Actuar (dos cualesquiera)'


def test_validate_pdf_professions_matches_talent_specialization_count_phrasing(db, make_talent):
    from app.models.talent import Talent
    make_talent(name_es='Especialista en armas (Varios)')
    professions = [{
        'name': 'Artista', 'type': 'basic',
        'talents_raw': 'Especialista en armas (Arrojadizas)',
    }]

    result = admin_routes._validate_pdf_professions(professions, [], Talent.query.all())
    assert result[0]['unmatched_talents'] == []


def test_match_and_save_skills_links_specialization_count_phrasing(
    app, db, make_profession, make_skill,
):
    skill = make_skill(name_es='Actuar (Varios)')
    prof = make_profession(name='Artista')
    with app.test_request_context():
        admin_routes._match_and_save_skills(prof, skills_raw='Actuar (dos cualesquiera)')
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    assert len(saved) == 1
    assert saved[0].skill_id == skill.id
    assert saved[0].specialization == 'dos cualesquiera'


# ── "<N> cualquiera(s) de las/los siguientes: A, B, C" enumeration ──────────
# WFRP2's "pick N of the following" phrasing. For N == 1 all listed items form
# one shared choice_group (pick exactly one); the schema has no way to represent
# "pick exactly K of N" for K > 1, so those are kept individually matchable but
# ungrouped - the admin can regroup manually at integration time.

def test_validate_pdf_professions_strips_choose_one_connector_for_display(db, make_skill):
    make_skill(name_es='Percepción')
    make_skill(name_es='Callejeo')
    make_skill(name_es='Nadar')
    professions = [{
        'name': 'Artista', 'type': 'basic',
        'skills_raw': 'Percepción, Una cualquiera de las siguientes: Callejeo, Nadar',
    }]

    from app.models.skill import Skill
    result = admin_routes._validate_pdf_professions(professions, Skill.query.all(), [])
    assert result[0]['unmatched_skills'] == []
    assert 'cualquiera de las siguientes' not in result[0]['skills_raw'].lower()
    assert result[0]['skills_raw'] == 'Percepción, Callejeo, Nadar'


def test_match_and_save_skills_groups_choose_one_of_list_under_shared_choice_group(
    app, db, make_profession, make_skill,
):
    a = make_skill(name_es='Adiestrar animales')
    b = make_skill(name_es='Carisma animal')
    c = make_skill(name_es='Escalar')
    prof = make_profession(name='Artista')
    with app.test_request_context():
        admin_routes._match_and_save_skills(
            prof,
            skills_raw='Una cualquiera de las siguientes: Adiestrar animales, Carisma animal, Escalar',
        )
    db.session.commit()

    saved = ProfessionSkill.query.filter_by(profession_id=prof.id).all()
    groups = {ps.choice_group for ps in saved}
    assert None not in groups
    assert len(groups) == 1
    assert {ps.skill_id for ps in saved} == {a.id, b.id, c.id}


def test_match_and_save_talents_choose_two_of_list_leaves_items_ungrouped(
    app, db, make_profession, make_talent,
):
    """'Dos cualesquiera de los siguientes' means pick exactly 2 of N - the
    choice_group column can't represent that, so each item is saved individually
    matchable (ungrouped) rather than corrupted or silently dropped."""
    a = make_talent(name_es='Certero')
    b = make_talent(name_es='Lucha')
    c = make_talent(name_es='Muy fuerte')
    prof = make_profession(name='Artista')
    with app.test_request_context():
        admin_routes._match_and_save_talents(
            prof,
            talents_raw='Dos cualesquiera de los siguientes: Certero, Lucha, Muy fuerte',
        )
    db.session.commit()

    saved = ProfessionTalent.query.filter_by(profession_id=prof.id).all()
    assert {pt.talent_id for pt in saved} == {a.id, b.id, c.id}
    assert all(pt.choice_group is None for pt in saved)


# ── Job/cache file-based persistence ─────────────────────────────────────────

def test_write_and_read_job_roundtrip():
    admin_routes._write_job('job-abc', {'percent': 50, 'stage': 'Procesando'})
    job = admin_routes._read_job('job-abc')
    assert job == {'percent': 50, 'stage': 'Procesando'}


def test_read_job_returns_none_for_missing():
    assert admin_routes._read_job('does-not-exist') is None


def test_write_and_read_cache_roundtrip():
    admin_routes._write_cache('cache-abc', {'result': {'professions': []}, 'filename': 'x.pdf'})
    cached = admin_routes._read_cache('cache-abc')
    assert cached['filename'] == 'x.pdf'


def test_cache_expires_after_ttl():
    admin_routes._write_cache('cache-old', {'result': {}, 'filename': 'old.pdf'})
    path = admin_routes._cache_path('cache-old')
    old_time = time.time() - admin_routes._CACHE_TTL - 60
    os.utime(path, (old_time, old_time))

    assert admin_routes._read_cache('cache-old') is None
    assert not os.path.exists(path)


def test_job_and_cache_ids_are_sanitized_against_path_traversal():
    path = admin_routes._job_path('../../etc/passwd')
    assert '..' not in os.path.basename(path)
    assert path.startswith(admin_routes._JOBS_DIR)


# ── Routes: upload / progress / result / resume ─────────────────────────────

def test_pdf_upload_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/pdf')
    assert resp.status_code == 403


def test_pdf_upload_rejects_missing_file(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/pdf', data={}, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json()['error']


def test_pdf_upload_rejects_non_pdf_extension(client, admin_user, login_as):
    import io
    login_as(client, admin_user, 'adminpass123')
    data = {'pdf_file': (io.BytesIO(b'not a pdf'), 'careers.txt')}
    resp = client.post('/admin/pdf', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert 'PDF' in resp.get_json()['error']


def test_pdf_progress_returns_404_for_unknown_job(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/pdf/progress/unknown-job-id')
    assert resp.status_code == 404


def test_pdf_progress_reports_job_state(client, admin_user, login_as):
    admin_routes._write_job('job-1', {
        'percent': 42, 'stage': 'OCR en curso', 'done': False, 'error': None,
    })
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/pdf/progress/job-1')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {'percent': 42, 'stage': 'OCR en curso', 'done': False, 'error': None}


def test_pdf_result_redirects_if_job_not_done(client, admin_user, login_as):
    admin_routes._write_job('job-2', {'percent': 10, 'done': False})
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/pdf/result/job-2', follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/admin/pdf'


def test_pdf_result_renders_review_and_persists_cache(client, admin_user, login_as):
    admin_routes._write_job('job-3', {
        'done': True, 'error': None,
        'result': {'professions': [{'name': 'Alborotador', 'type': 'basic'}], 'pages': [], 'errors': []},
        'filename': 'careers.pdf',
    })
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/pdf/result/job-3')
    assert resp.status_code == 200
    assert 'Alborotador'.encode('utf-8') in resp.data

    # Job file consumed, cache file created for resume - this is the fix for
    # bug #2 (cache used to live under tempfile.gettempdir() and vanish on redeploy).
    assert admin_routes._read_job('job-3') is None
    cached = admin_routes._read_cache('job-3')
    assert cached is not None
    assert cached['filename'] == 'careers.pdf'


def test_pdf_result_splits_summary_into_registered_and_unregistered_tables_with_anchors(
    db, client, admin_user, login_as, make_profession,
):
    """The triage summary is split into two collapsible tables (feature request:
    large imports shouldn't bury the ones needing review under dozens of
    already-registered rows), and each row links directly to its profession
    card further down the page."""
    make_profession(name='Alborotador')
    admin_routes._write_job('job-split', {
        'done': True, 'error': None,
        'result': {
            'professions': [
                {'name': 'Alborotador', 'type': 'basic'},  # exact match -> "registradas"
                {'name': 'Bufón Errante', 'type': 'basic'},  # new -> "no registradas"
            ],
            'pages': [], 'errors': [],
        },
        'filename': 'careers.pdf',
    })
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/pdf/result/job-split')
    body = resp.data.decode('utf-8')

    assert 'Ya registradas' in body
    assert 'No registradas' in body
    assert 'id="prof-card-1"' in body
    assert 'id="prof-card-2"' in body
    assert 'href="#prof-card-1"' in body
    assert 'href="#prof-card-2"' in body


def test_pdf_resume_renders_from_cache(client, admin_user, login_as):
    admin_routes._write_cache('cache-resume', {
        'result': {'professions': [{'name': 'Bufón', 'type': 'basic'}], 'pages': [], 'errors': []},
        'filename': 'careers.pdf',
    })
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/pdf/resume/cache-resume')
    assert resp.status_code == 200
    assert b'Buf\xc3\xb3n' in resp.data


def test_pdf_resume_redirects_when_cache_missing(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/pdf/resume/does-not-exist', follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/admin/pdf'


# ── Route: pdf_save (the actual save-time bug fixes) ────────────────────────

def test_pdf_save_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/admin/pdf/guardar', data={'name': 'Algo'})
    assert resp.status_code == 403


def test_pdf_save_requires_name(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/pdf/guardar', data={'name': ''}, follow_redirects=True)
    assert resp.status_code == 200
    assert Profession.query.count() == 0


def test_pdf_save_create_uses_confirmed_chips_not_stale_english(db, client, admin_user, login_as, make_skill):
    """Direct regression test for bug #1 via the real save endpoint."""
    correct = make_skill(name_es='Percepción')
    make_skill(name_es='Callejeo')

    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/pdf/guardar', data={
        'name': 'Explorador', 'type': 'basic',
        'skills_raw': 'Percepción',
        'skills_raw_en': 'Street Wise',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Explorador').first()
    assert prof is not None
    saved_skill_ids = {ps.skill_id for ps in ProfessionSkill.query.filter_by(profession_id=prof.id).all()}
    assert saved_skill_ids == {correct.id}


def test_pdf_save_create_links_confident_exits_and_leaves_rest_pending(db, client, admin_user, login_as, make_profession):
    """Regression test for bug #3: confident matches get linked directly;
    only genuinely unmatched names fall back to the pending-link text."""
    target = make_profession(name='Veterano', type='advanced')

    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/pdf/guardar', data={
        'name': 'Soldado', 'type': 'basic',
        'exits_raw': 'Veterano, Profesión Inventada',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Soldado').first()
    assert target in prof.exits
    assert 'Profesión Inventada' in (prof.description or '')
    assert 'SALIDAS PENDIENTES' in (prof.description or '')


def test_pdf_save_create_links_confident_entries_in_reverse_direction(db, client, admin_user, login_as, make_profession):
    source = make_profession(name='Alborotador', type='basic')

    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/pdf/guardar', data={
        'name': 'Ladrón', 'type': 'basic',
        'entries_raw': 'Alborotador',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Ladrón').first()
    db.session.refresh(source)
    assert prof in source.exits


def test_pdf_save_update_mode_overwrites_existing_profession(db, client, admin_user, login_as, make_profession, make_skill):
    prof = make_profession(name='Alborotador', type='basic')
    skill = make_skill(name_es='Percepción')

    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/pdf/guardar', data={
        'name': 'Alborotador', 'type': 'basic',
        'save_mode': 'update', 'existing_prof_id': str(prof.id),
        'skills_raw': 'Percepción',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(prof)
    saved_skill_ids = {ps.skill_id for ps in ProfessionSkill.query.filter_by(profession_id=prof.id).all()}
    assert saved_skill_ids == {skill.id}


def test_pdf_save_skip_mode_redirects_without_changes(db, client, admin_user, login_as, make_profession):
    prof = make_profession(name='Alborotador', type='basic')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/pdf/guardar', data={
        'name': 'Alborotador', 'save_mode': 'skip', 'existing_prof_id': str(prof.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Profession.query.count() == 1


def test_pdf_save_blocks_silent_duplicate_from_resumed_session(db, client, admin_user, login_as):
    """Direct regression test for the real incident: a cached/resumed review
    session gets submitted a second time (e.g. after the profession was
    already saved once), with no existing_prof_id known at parse time. The
    save-time safety net must catch this instead of creating a duplicate."""
    login_as(client, admin_user, 'adminpass123')

    first = client.post('/admin/pdf/guardar', data={'name': 'Alborotador', 'type': 'basic'},
                        follow_redirects=True)
    assert first.status_code == 200
    assert Profession.query.filter_by(name='Alborotador').count() == 1

    # Same PDF review session submitted again - no existing_prof_id this time.
    second = client.post('/admin/pdf/guardar', data={'name': 'Alborotador', 'type': 'basic'},
                         follow_redirects=True)
    assert second.status_code == 200
    assert Profession.query.filter_by(name='Alborotador').count() == 1
    assert 'ya existe una profesión'.encode('utf-8') in second.data.lower()


def test_pdf_save_duplicate_guard_is_case_insensitive(db, client, admin_user, login_as, make_profession):
    make_profession(name='Alborotador', type='basic')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/pdf/guardar', data={'name': 'ALBOROTADOR', 'type': 'basic'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert Profession.query.count() == 1
