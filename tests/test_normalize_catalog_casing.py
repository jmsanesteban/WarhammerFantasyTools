"""Tests for the `flask normalize-catalog-casing` one-off command: the
Habilidades/Talentos catalog was originally seeded with name_es in ALL CAPS,
which made the PDF-import review page's canonicalization (rewrite a matched
chip to the catalog's exact name_es) look inconsistent next to the Title-Case
text extracted from the book.
"""


def test_normalize_catalog_casing_rewrites_known_all_caps_names(app, db, make_skill, make_talent):
    make_skill(name_es='PERCEPCIÓN')
    make_talent(name_es='CERTERO')

    result = app.test_cli_runner().invoke(args=['normalize-catalog-casing'])
    assert result.exit_code == 0

    from app.models.skill import Skill
    from app.models.talent import Talent
    assert Skill.query.filter_by(name_es='Percepción').count() == 1
    assert Talent.query.filter_by(name_es='Certero').count() == 1


def test_normalize_catalog_casing_leaves_already_correct_names_untouched(app, db, make_skill):
    make_skill(name_es='Percepción')

    result = app.test_cli_runner().invoke(args=['normalize-catalog-casing'])
    assert result.exit_code == 0

    from app.models.skill import Skill
    assert Skill.query.filter_by(name_es='Percepción').count() == 1


def test_normalize_catalog_casing_is_idempotent(app, db, make_skill):
    make_skill(name_es='HABLAR IDIOMA (varios)')

    runner = app.test_cli_runner()
    runner.invoke(args=['normalize-catalog-casing'])
    result = runner.invoke(args=['normalize-catalog-casing'])
    assert result.exit_code == 0

    from app.models.skill import Skill
    assert Skill.query.filter_by(name_es='Hablar idioma (Varios)').count() == 1
