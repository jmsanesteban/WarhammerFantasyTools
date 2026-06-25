from datetime import datetime
from app.extensions import db


class Talent(db.Model):
    __tablename__ = 'talents'

    id = db.Column(db.Integer, primary_key=True)
    name_es = db.Column(db.String(150), nullable=False, index=True)
    name_en = db.Column(db.String(150), nullable=True)
    description = db.Column(db.Text, nullable=True)
    max_times = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Talent {self.name_es}>'
