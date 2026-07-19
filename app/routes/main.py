import os
from flask import Blueprint, render_template, send_from_directory, current_app, abort
from app.models.profession import Profession
from app.models.skill import Skill
from app.models.talent import Talent

main_bp = Blueprint('main', __name__, template_folder='../templates')


@main_bp.route('/uploads/<path:filename>')
def uploaded_file(filename):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    safe_path = os.path.join(upload_folder, filename)
    if not os.path.abspath(safe_path).startswith(os.path.abspath(upload_folder)):
        abort(403)
    return send_from_directory(upload_folder, filename)


@main_bp.route('/')
def index():
    total_professions = Profession.query.count()
    total_skills = Skill.query.count()
    total_talents = Talent.query.count()
    recent_professions = Profession.query.order_by(Profession.created_at.desc()).limit(6).all()
    return render_template(
        'index.html',
        total_professions=total_professions,
        total_skills=total_skills,
        total_talents=total_talents,
        recent_professions=recent_professions,
    )


@main_bp.app_errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html', error=e), 403


@main_bp.app_errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404


@main_bp.app_errorhandler(500)
def server_error(e):
    return render_template('errors/500.html'), 500
