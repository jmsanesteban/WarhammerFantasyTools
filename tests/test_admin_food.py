"""Tests for the admin "Comida y bebida" section: dedicated Exportar/Importar
recetas (thin wrappers around backup_service, already covered at the service
level in test_backup_service.py), the recetas-hechas PDF importer (parsing +
review-before-commit + image extraction) and the imagenes_comidas folder
photo sync."""
import io
import json

import fitz
from PIL import Image

from app.extensions import db
from app.models.food import CookingMethod, Ingredient, Recipe
from app.services.food_pdf_service import parse_recetas_pdf, sync_recipe_images_from_folder


def _tiny_jpeg_bytes(color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new('RGB', (12, 12), color=color).save(buf, format='JPEG')
    return buf.getvalue()


def _make_recetas_pdf(blocks):
    """blocks: list of (lines, image_bytes_or_None). Builds a minimal PDF
    with one page, each block's lines inserted top-to-bottom as plain text,
    optionally followed by an embedded image - close enough to the real
    "Recetas hechas.pdf" layout for page.get_text() to reproduce the same
    line-by-line shape the parser's regexes expect."""
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for lines, image_bytes in blocks:
        for line in lines:
            page.insert_text((50, y), line, fontsize=10)
            y += 14
        if image_bytes:
            page.insert_image(fitz.Rect(400, y - 14 * len(lines), 450, y), stream=image_bytes)
        y += 30
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


_FRUTA_DULCE_LINES = [
    'FRUTA DULCE',
    'Vigor : 15',
    'Moral : 8',
    'Método de cocina/recalentar :  Almíbar  /  NO',
    'Duración : 100 días',
    'Calidad : NORMAL (5)',
    'Ingrediente 1: Frutas',
    'Ingrediente 2: Nada',
    'Ingrediente 3: Nada',
    'Ingrediente 4: Nada',
    'Condimento 1: Miel',
    'Condimento 2: Nada',
    'Coste Taberna',
    'Coste Ingredientes',
    '7 p',
    '20 p',
]

_EMPANADILLA_LINES = [
    'EMPANADILLA HALFLING',
    'Vigor : 10',
    'Moral : 0',
    'Método de cocina/recalentar :  *  /  NO',
    'Duración : 100 días',
    'Calidad : *',
    'Ingrediente secreto, sabor especial.',
    'Coste Taberna',
    'Coste Ingredientes',
    '1 p',
    '* p',
]


def _seed_method_and_ingredients(app):
    with app.app_context():
        db.session.add(CookingMethod(nombre='Almíbar', duracion_dias=100, complejidad_base=1,
                                      ingredientes_permitidos=1, condimentos_permitidos=1))
        db.session.add(Ingredient(nombre='Frutas', coste_docena=5))
        db.session.add(Ingredient(nombre='Miel', coste_docena=5))
        db.session.commit()


def test_parse_recetas_pdf_extracts_normal_recipe_with_image(app, db):
    _seed_method_and_ingredients(app)
    pdf_bytes = _make_recetas_pdf([(_FRUTA_DULCE_LINES, _tiny_jpeg_bytes())])

    with app.app_context():
        rows = parse_recetas_pdf(pdf_bytes)

    assert len(rows) == 1
    row = rows[0]
    assert row['nombre'] == 'FRUTA DULCE'
    assert row['vigor'] == 15
    assert row['moral'] == 8
    assert row['metodo_nombre'] == 'Almíbar'  # resolved despite the PDF's own accent-dropping typo risk
    assert row['calidad'] == 'Normal'
    assert row['complejidad'] == 5
    assert row['duracion_dias'] == 100
    assert row['recalentar'] is False
    assert row['precio_compra_peniques'] == 7
    assert row['coste_creacion_peniques'] == 20
    assert row['ingredientes_nombres'] == ['Frutas']
    assert row['condimentos_nombres'] == ['Miel']
    assert row['existe_ya'] is False
    assert row['image_bytes'] is not None
    assert row['image_ext'] in ('jpeg', 'jpg')


def test_parse_recetas_pdf_handles_special_recipe_block(app, db):
    _seed_method_and_ingredients(app)
    pdf_bytes = _make_recetas_pdf([(_EMPANADILLA_LINES, None)])

    with app.app_context():
        rows = parse_recetas_pdf(pdf_bytes)

    assert len(rows) == 1
    row = rows[0]
    assert row['nombre'] == 'EMPANADILLA HALFLING'
    assert row['calidad'] is None
    assert row['solo_compra'] is True
    assert row['cooking_method_id'] is None


def test_parse_recetas_pdf_flags_existing_recipe(app, db):
    _seed_method_and_ingredients(app)
    with app.app_context():
        db.session.add(Recipe(nombre='FRUTA DULCE', vigor=1, moral=1))
        db.session.commit()

    pdf_bytes = _make_recetas_pdf([(_FRUTA_DULCE_LINES, None)])
    with app.app_context():
        rows = parse_recetas_pdf(pdf_bytes)

    assert rows[0]['existe_ya'] is True


def test_comida_import_pdf_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/comida/importar-pdf')
    assert resp.status_code == 403


def test_comida_import_pdf_confirmar_creates_recipe_with_image(app, db, client, admin_user, login_as, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    _seed_method_and_ingredients(app)
    login_as(client, admin_user, 'adminpass123')

    image_bytes = _tiny_jpeg_bytes()
    pdf_bytes = _make_recetas_pdf([(_FRUTA_DULCE_LINES, image_bytes)])

    resp = client.post('/admin/comida/importar-pdf', data={'file': (io.BytesIO(pdf_bytes), 'recetas.pdf')},
                        content_type='multipart/form-data')
    assert resp.status_code == 200
    assert 'FRUTA DULCE'.encode('utf-8') in resp.data

    with app.app_context():
        row = parse_recetas_pdf(pdf_bytes)[0]
        row.pop('image_bytes', None)
        import base64
        row['image_b64'] = base64.b64encode(image_bytes).decode('ascii')

    resp = client.post('/admin/comida/importar-pdf/confirmar', data={
        'importar_0': 'on', 'receta_0': json.dumps(row),
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        recipe = Recipe.query.filter_by(nombre='FRUTA DULCE').first()
        assert recipe is not None
        assert recipe.vigor == 15
        assert recipe.image_path is not None
        assert recipe.image_path.replace('\\', '/').startswith('recetas/')


def test_comida_import_pdf_confirmar_skips_if_created_meanwhile(app, db, client, admin_user, login_as):
    """Re-checks at commit time even if the review screen was stale."""
    _seed_method_and_ingredients(app)
    login_as(client, admin_user, 'adminpass123')

    row = {
        'nombre': 'FRUTA DULCE', 'vigor': 15, 'moral': 8, 'cooking_method_id': None,
        'calidad': 'Normal', 'complejidad': 5, 'duracion_dias': 100, 'recalentar': False,
        'precio_compra_peniques': 7, 'coste_creacion_peniques': 20, 'solo_compra': False, 'notas': None,
        'ingrediente_1_id': None, 'ingrediente_2_id': None, 'ingrediente_3_id': None, 'ingrediente_4_id': None,
        'condimento_1_id': None, 'condimento_2_id': None, 'image_b64': None, 'image_ext': None,
    }
    with app.app_context():
        db.session.add(Recipe(nombre='FRUTA DULCE', vigor=1, moral=1))
        db.session.commit()

    resp = client.post('/admin/comida/importar-pdf/confirmar', data={
        'importar_0': 'on', 'receta_0': json.dumps(row),
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert Recipe.query.filter_by(nombre='FRUTA DULCE').count() == 1


def test_sync_recipe_images_only_fills_missing_photos(app, db, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        db.session.add(Recipe(nombre='Sopa sin foto', vigor=1, moral=1))
        db.session.add(Recipe(nombre='Sopa con foto', vigor=1, moral=1, image_path='recetas/existing.jpg'))
        db.session.commit()

    upload_folder = app.config['UPLOAD_FOLDER']
    import os
    folder = os.path.join(upload_folder, 'imagenes_comidas')
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'Sopa sin foto.jpg'), 'wb') as f:
        f.write(_tiny_jpeg_bytes())
    with open(os.path.join(folder, 'Sopa con foto.jpg'), 'wb') as f:
        f.write(_tiny_jpeg_bytes())
    with open(os.path.join(folder, 'Receta desconocida.jpg'), 'wb') as f:
        f.write(_tiny_jpeg_bytes())

    with app.app_context():
        summary = sync_recipe_images_from_folder()

    assert summary['linked'] == ['Sopa sin foto']
    assert summary['already_had_photo'] == ['Sopa con foto']
    assert summary['unmatched_files'] == ['Receta desconocida.jpg']

    with app.app_context():
        recipe = Recipe.query.filter_by(nombre='Sopa sin foto').first()
        assert recipe.image_path.replace('\\', '/') == 'recetas/Sopa_sin_foto.jpg'
        untouched = Recipe.query.filter_by(nombre='Sopa con foto').first()
        assert untouched.image_path == 'recetas/existing.jpg'  # never overwritten


def test_sync_recipe_images_matches_filenames_missing_the_word_de(app, db, tmp_path):
    """Real-world gotcha found manually this session: some photo filenames
    drop the "de" connector the recipe's own nombre keeps (e.g. "Menestra
    verduras invernales.jpg" for "Menestra de verduras invernales")."""
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        db.session.add(Recipe(nombre='Menestra de verduras invernales', vigor=1, moral=1))
        db.session.add(Recipe(nombre='Ración de cecina', vigor=1, moral=1))
        db.session.commit()

    import os
    folder = os.path.join(str(tmp_path), 'imagenes_comidas')
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'Menestra verduras invernales.jpg'), 'wb') as f:
        f.write(_tiny_jpeg_bytes())
    with open(os.path.join(folder, 'Ración cecina.jpg'), 'wb') as f:
        f.write(_tiny_jpeg_bytes())

    with app.app_context():
        summary = sync_recipe_images_from_folder()

    assert set(summary['linked']) == {'Menestra de verduras invernales', 'Ración de cecina'}
    assert summary['unmatched_files'] == []


def test_comida_sync_fotos_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/admin/comida/sincronizar-fotos')
    assert resp.status_code == 403


def test_comida_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/comida/exportar')
    assert resp.status_code == 403


def test_comida_export_returns_recipes_json(client, admin_user, login_as, app, db):
    with app.app_context():
        db.session.add(Recipe(nombre='Receta exportable', vigor=1, moral=1))
        db.session.commit()
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/admin/comida/exportar')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert any(r['nombre'] == 'Receta exportable' for r in data)


def test_food_home_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/comida')
    assert resp.status_code == 403
