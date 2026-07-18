from flask import Blueprint, render_template, request, flash
from app.models.profession import Profession
from app.services.pathfinder_service import (
    build_graph, find_paths, find_path_with_waypoints, compute_path_stats,
)
from app.utils import require_permission

pathfinder_bp = Blueprint('pathfinder', __name__, template_folder='../templates')


@pathfinder_bp.route('/', methods=['GET', 'POST'])
@require_permission('pathfinder.use')
def index():
    professions = Profession.query.order_by(Profession.name).all()
    results = None
    start_id = None
    end_id = None
    waypoint_ids = []

    if request.method == 'POST':
        try:
            start_id = int(request.form.get('start_id', 0))
            end_id = int(request.form.get('end_id', 0))
            waypoint_ids = [int(w) for w in request.form.getlist('waypoint_id') if w.strip()]
        except (ValueError, TypeError):
            flash('Selecciona una profesión de inicio y una de destino.', 'danger')
            return render_template('pathfinder/index.html', professions=professions)

        if start_id == end_id:
            flash('La profesión de inicio y destino deben ser distintas.', 'warning')
            return render_template('pathfinder/index.html', professions=professions,
                                   start_id=start_id, end_id=end_id, waypoint_ids=waypoint_ids)

        G = build_graph(professions)
        prof_map = {p.id: p for p in professions}

        if waypoint_ids:
            stops = [start_id] + waypoint_ids + [end_id]
            route = find_path_with_waypoints(G, stops)
            if not route:
                flash('No se encontró ningún camino que pase por todos esos puntos intermedios.', 'info')
            else:
                stats = compute_path_stats(route['path_ids'], prof_map)
                branch_points_named = {
                    idx: prof_map[src_id].name
                    for idx, src_id in route['branch_points'].items() if src_id in prof_map
                }
                results = [{
                    'path_ids': route['path_ids'],
                    'path_steps': [{'id': pid, 'name': prof_map[pid].name} for pid in route['path_ids'] if pid in prof_map],
                    'branch_points': branch_points_named,
                    'stats': stats,
                    'hops': len(route['path_ids']) - 1,
                }]
        else:
            paths = find_paths(G, start_id, end_id, max_paths=5, cutoff=10)
            if not paths:
                flash('No se encontró ningún camino entre esas dos profesiones.', 'info')
            else:
                results = []
                for path_ids in paths:
                    stats = compute_path_stats(path_ids, prof_map)
                    results.append({
                        'path_ids': path_ids,
                        'path_steps': [{'id': pid, 'name': prof_map[pid].name} for pid in path_ids if pid in prof_map],
                        'branch_points': {},
                        'stats': stats,
                        'hops': len(path_ids) - 1,
                    })

    return render_template(
        'pathfinder/index.html',
        professions=professions,
        results=results,
        start_id=start_id,
        end_id=end_id,
        waypoint_ids=waypoint_ids,
    )
