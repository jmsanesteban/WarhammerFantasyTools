"""Idempotent seed of the Comida y bebida catalog (métodos de cocina,
ingredientes, compatibilidad, recetas, bebidas) from app/data/food/*.json —
same read-existing-then-insert-missing pattern as the Synonym seed in
app/__init__.py. Safe to call on every `flask init-db`."""
import json
import os

from app.extensions import db
from app.models.food import CookingMethod, Ingredient, IngredientCookingMethod, Recipe, Drink

_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'food')


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding='utf-8') as f:
        return json.load(f)


def seed_food_catalog() -> int:
    """Returns the number of rows inserted or backfilled (0 if the catalog is
    already fully seeded)."""
    added = 0

    existing_methods = {m.nombre: m for m in CookingMethod.query.all()}
    for row in _load('cooking_methods.json'):
        if row['nombre'] not in existing_methods:
            method = CookingMethod(**row)
            db.session.add(method)
            existing_methods[row['nombre']] = method
            added += 1
    db.session.flush()

    existing_ingredients = {i.nombre: i for i in Ingredient.query.all()}
    for row in _load('ingredients.json'):
        if row['nombre'] not in existing_ingredients:
            ingredient = Ingredient(**row)
            db.session.add(ingredient)
            existing_ingredients[row['nombre']] = ingredient
            added += 1
    db.session.flush()

    existing_compat = {
        (c.ingredient_id, c.cooking_method_id) for c in IngredientCookingMethod.query.all()
    }
    for row in _load('ingredient_compatibility.json'):
        ingredient = existing_ingredients[row['ingrediente']]
        method = existing_methods[row['metodo']]
        if (ingredient.id, method.id) not in existing_compat:
            db.session.add(IngredientCookingMethod(
                ingredient_id=ingredient.id, cooking_method_id=method.id, estado=row['estado'],
            ))
            added += 1
    db.session.flush()

    existing_recipes = {r.nombre: r for r in Recipe.query.all()}
    for row in _load('recipes.json'):
        if row['nombre'] in existing_recipes:
            # Backfill columns added after this book recipe was first seeded
            # (e.g. 'complejidad', introduced alongside the Fase 2 proposal
            # workflow) - book recipes are never otherwise touched here.
            recipe = existing_recipes[row['nombre']]
            if recipe.complejidad is None and row['complejidad'] is not None:
                recipe.complejidad = row['complejidad']
                added += 1
            continue
        method = existing_methods.get(row['metodo_cocina']) if row['metodo_cocina'] else None

        def ing_id(name):
            return existing_ingredients[name].id if name and name != 'Nada' else None

        db.session.add(Recipe(
            nombre=row['nombre'], vigor=row['vigor'], moral=row['moral'],
            cooking_method_id=method.id if method else None,
            calidad=row['calidad'], duracion_dias=row['duracion_dias'], recalentar=row['recalentar'],
            coste_creacion_peniques=row['coste_creacion_peniques'],
            precio_compra_peniques=row['precio_compra_peniques'], complejidad=row['complejidad'],
            solo_compra=row['solo_compra'], notas=row['notas'],
            status='aprobada',
            ingrediente_1_id=ing_id(row['ingrediente_1']), ingrediente_2_id=ing_id(row['ingrediente_2']),
            ingrediente_3_id=ing_id(row['ingrediente_3']), ingrediente_4_id=ing_id(row['ingrediente_4']),
            condimento_1_id=ing_id(row['condimento_1']), condimento_2_id=ing_id(row['condimento_2']),
        ))
        added += 1

    existing_drinks = {(d.nombre, d.origen) for d in Drink.query.all()}
    for row in _load('drinks.json'):
        if (row['nombre'], row['origen']) not in existing_drinks:
            db.session.add(Drink(**row))
            added += 1

    if added:
        db.session.commit()
    return added
