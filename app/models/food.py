from app.extensions import db


class CookingMethod(db.Model):
    """A cooking method (Crudo, Ahumado, Guisado...) with its base vigor/moral/
    coste/duración and how many ingredient/condiment slots a recipe using it may fill."""
    __tablename__ = 'cooking_methods'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    vigor = db.Column(db.Integer, nullable=False, default=0)
    moral = db.Column(db.Integer, nullable=False, default=0)
    coste = db.Column(db.Integer, nullable=False, default=0)
    duracion_dias = db.Column(db.Integer, nullable=False)
    complejidad_base = db.Column(db.Integer, nullable=False, default=0)
    ingredientes_permitidos = db.Column(db.Integer, nullable=False, default=1)
    condimentos_permitidos = db.Column(db.Integer, nullable=False, default=0)
    elementos_necesarios = db.Column(db.String(100), nullable=True)
    habilidad = db.Column(db.String(100), nullable=True)
    recalentar = db.Column(db.Boolean, nullable=False, default=False)
    descripcion = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<CookingMethod {self.nombre}>'


class Ingredient(db.Model):
    """A raw ingredient/condiment family (Verduras, Carne superior, Sal...) with its
    own vigor/moral/coste per docena, independent of the cooking method used."""
    __tablename__ = 'ingredients'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    vigor = db.Column(db.Integer, nullable=False, default=0)
    moral = db.Column(db.Integer, nullable=False, default=0)
    coste_docena = db.Column(db.Integer, nullable=False, default=0)
    descripcion = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Ingredient {self.nombre}>'


class IngredientCookingMethod(db.Model):
    """Compatibility matrix: whether an Ingredient can be used with a CookingMethod
    as a regular ingredient ('si'), not at all ('no'), or only as a condiment ('condimento')."""
    __tablename__ = 'ingredient_cooking_methods'

    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredients.id', ondelete='CASCADE'), nullable=False)
    cooking_method_id = db.Column(db.Integer, db.ForeignKey('cooking_methods.id', ondelete='CASCADE'), nullable=False)
    estado = db.Column(db.String(12), nullable=False, default='no')  # 'si' | 'no' | 'condimento'

    ingredient = db.relationship('Ingredient', backref='compatibilidades')
    cooking_method = db.relationship('CookingMethod', backref='compatibilidades')

    __table_args__ = (
        db.UniqueConstraint('ingredient_id', 'cooking_method_id', name='uq_ingredient_cooking_method'),
    )


class Recipe(db.Model):
    """A recipe: either produced from a CookingMethod + up to 4 ingredients + 2
    condiments (book examples, and later user-created ones), or 'solo_compra' —
    a special recipe that can only be bought, never crafted."""
    __tablename__ = 'recipes'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), unique=True, nullable=False)
    vigor = db.Column(db.Integer, nullable=False, default=0)
    moral = db.Column(db.Integer, nullable=False, default=0)
    cooking_method_id = db.Column(db.Integer, db.ForeignKey('cooking_methods.id'), nullable=True)
    calidad = db.Column(db.String(20), nullable=True)  # 'Mala' | 'Normal' | 'Buena' | 'Excelente'
    duracion_dias = db.Column(db.Integer, nullable=True)
    recalentar = db.Column(db.Boolean, nullable=False, default=False)
    coste_creacion_peniques = db.Column(db.Integer, nullable=True)  # 12 raciones
    precio_compra_peniques = db.Column(db.Integer, nullable=True)  # 1 ración ya cocinada
    # complejidad_base del método + 1 por ingrediente relleno + 2 por condimento relleno
    complejidad = db.Column(db.Integer, nullable=True)
    solo_compra = db.Column(db.Boolean, nullable=False, default=False)
    notas = db.Column(db.Text, nullable=True)

    # Fase 2: propuestas de usuarios en revisión. Las recetas del libro (sembradas
    # por food_seed_service) quedan 'aprobada' con created_by_id=None.
    status = db.Column(db.String(20), nullable=False, default='aprobada')  # 'pendiente' | 'aprobada' | 'rechazada'
    image_path = db.Column(db.String(300), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    requested_at = db.Column(db.DateTime, nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])

    ingrediente_1_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=True)
    ingrediente_2_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=True)
    ingrediente_3_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=True)
    ingrediente_4_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=True)
    condimento_1_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=True)
    condimento_2_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=True)

    cooking_method = db.relationship('CookingMethod', lazy='joined')
    ingrediente_1 = db.relationship('Ingredient', foreign_keys=[ingrediente_1_id])
    ingrediente_2 = db.relationship('Ingredient', foreign_keys=[ingrediente_2_id])
    ingrediente_3 = db.relationship('Ingredient', foreign_keys=[ingrediente_3_id])
    ingrediente_4 = db.relationship('Ingredient', foreign_keys=[ingrediente_4_id])
    condimento_1 = db.relationship('Ingredient', foreign_keys=[condimento_1_id])
    condimento_2 = db.relationship('Ingredient', foreign_keys=[condimento_2_id])

    @property
    def ingredientes(self):
        return [i for i in (self.ingrediente_1, self.ingrediente_2, self.ingrediente_3, self.ingrediente_4) if i]

    @property
    def condimentos(self):
        return [c for c in (self.condimento_1, self.condimento_2) if c]

    def __repr__(self):
        return f'<Recipe {self.nombre}>'


class Drink(db.Model):
    """A book drink — catalog only, no new drinks are ever created by users."""
    __tablename__ = 'drinks'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    origen = db.Column(db.String(50), nullable=False)  # nación/raza de origen
    disponibilidad = db.Column(db.String(20), nullable=True)
    calidad = db.Column(db.String(20), nullable=True)
    sabor = db.Column(db.String(20), nullable=True)  # categoría base: Extraño, Fuerte, Suave, Raro, Mala, Bueno...
    sabor_variante = db.Column(db.String(30), nullable=True)  # descriptor concreto cuando sabor es Extraño/Raro
    ui_texto = db.Column(db.String(100), nullable=True)  # cantidad para 1 Unidad de Intoxicación
    recipiente = db.Column(db.String(30), nullable=True)  # recipiente servido en taberna
    precio_taberna_peniques = db.Column(db.Integer, nullable=True)  # precio de 1 recipiente en taberna
    por_mayor_pct = db.Column(db.Integer, nullable=True)  # % descuento comprando por mayor (tonel), null = no disponible
    notas = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('nombre', 'origen', name='uq_drink_nombre_origen'),
    )

    def __repr__(self):
        return f'<Drink {self.nombre} ({self.origen})>'
