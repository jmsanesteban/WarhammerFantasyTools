"""Pure calculation of a Recipe's derived stats (vigor/moral/coste/precio/
duración/recalentar/complejidad) from its cooking method + ingredient/condiment
composition. Verified to reproduce every example recipe in the source book
exactly - see tests/test_food.py. No DB writes here."""


class RecipeCompositionError(ValueError):
    """A chosen ingredient/condiment (or slot count) isn't valid for the method."""


def calidad_from_complejidad(complejidad: int) -> str:
    """1-4 Mala, 5-8 Normal, 9-12 Buena, 13+ Excelente - verified against all
    25 example recipes in the book (calidad is never chosen by hand, it's a
    direct function of complejidad)."""
    if complejidad >= 13:
        return 'Excelente'
    if complejidad >= 9:
        return 'Buena'
    if complejidad >= 5:
        return 'Normal'
    return 'Mala'


def validate_and_calculate(cooking_method, ingredientes, condimentos):
    """cooking_method: a CookingMethod instance.
    ingredientes/condimentos: lists of Ingredient instances actually filled in
    (never include "Nada"/None slots), respectively at most
    cooking_method.ingredientes_permitidos / condimentos_permitidos long.
    Returns a dict of the computed fields. Raises RecipeCompositionError if the
    combination breaks the method's slot limits or compatibility matrix."""
    if len(ingredientes) > cooking_method.ingredientes_permitidos:
        raise RecipeCompositionError(
            f'El método "{cooking_method.nombre}" solo admite '
            f'{cooking_method.ingredientes_permitidos} ingrediente(s).'
        )
    if len(condimentos) > cooking_method.condimentos_permitidos:
        raise RecipeCompositionError(
            f'El método "{cooking_method.nombre}" solo admite '
            f'{cooking_method.condimentos_permitidos} condimento(s).'
        )

    compat = {row.ingredient_id: row.estado for row in cooking_method.compatibilidades}
    for ing in ingredientes:
        if compat.get(ing.id) != 'si':
            raise RecipeCompositionError(
                f'"{ing.nombre}" no se puede usar como ingrediente con el método "{cooking_method.nombre}".'
            )
    for cond in condimentos:
        if compat.get(cond.id) != 'condimento':
            raise RecipeCompositionError(
                f'"{cond.nombre}" no se puede usar como condimento con el método "{cooking_method.nombre}".'
            )

    usados = ingredientes + condimentos
    coste_creacion = cooking_method.coste + sum(i.coste_docena for i in usados)
    complejidad = cooking_method.complejidad_base + len(ingredientes) + 2 * len(condimentos)

    return dict(
        vigor=cooking_method.vigor + sum(i.vigor for i in usados),
        moral=cooking_method.moral + sum(i.moral for i in usados),
        coste_creacion_peniques=coste_creacion,
        precio_compra_peniques=round(coste_creacion / 12 * 4),
        duracion_dias=cooking_method.duracion_dias,
        recalentar=cooking_method.recalentar,
        complejidad=complejidad,
        calidad=calidad_from_complejidad(complejidad),
    )
