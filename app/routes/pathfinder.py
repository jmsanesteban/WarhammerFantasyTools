from flask import Blueprint, render_template, request, flash
from app.models.profession import Profession
from app.services.pathfinder_service import build_graph, find_paths, compute_path_stats

pathfinder_bp = Blueprint('pathfinder', __name__, template_folder='../templates')


@pathfinder_bp.route('/', methods=['GET', 'POST'])
def index():
    professions = Profession.query.order_by(Profession.name).all()
    results = None
    start_id = None
    end_id = None

    if request.method == 'POST':
        try:
            start_id = int(request.form.get('start_id', 0))
            end_id = int(request.form.get('end_id', 0))
        except (ValueError, TypeError):
            flash('Selecciona una profesión de inicio y una de destino.', 'danger')
            return render_template('pathfinder/index.html', professions=professions)

        if start_id == end_id:
            flash('La profesión de inicio y destino deben ser distintas.', 'warning')
            return render_template('pathfinder/index.html', professions=professions,
                                   start_id=start_id, end_id=end_id)

        G = build_graph(professions)
        paths = find_paths(G, start_id, end_id, max_paths=5, cutoff=10)

        if not paths:
            flash('No se encontró ningún camino entre esas dos profesiones.', 'info')
        else:
            prof_map = {p.id: p for p in professions}
            results = []
            for path_ids in paths:
                stats = compute_path_stats(path_ids, prof_map)
                results.append({
                    'path_ids': path_ids,
                    'path_names': [prof_map[pid].name for pid in path_ids if pid in prof_map],
                    'stats': stats,
                    'hops': len(path_ids) - 1,
                })

    return render_template(
        'pathfinder/index.html',
        professions=professions,
        results=results,
        start_id=start_id,
        end_id=end_id,
    )
