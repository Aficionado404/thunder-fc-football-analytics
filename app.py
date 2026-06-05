"""
app.py — Thunder FC (production upgrade)
Thin Flask app: wires config, blueprints, CSRF, logging, and DB teardown.
All business logic lives in services.py / ml.py / auth.py.
"""

import os
import json
import sqlite3
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify, g)
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from werkzeug.security import generate_password_hash, check_password_hash

from config   import get_config
from logger   import setup_logger
from db       import get_db, close_db, init_db
from auth     import (login_required, admin_required, coach_required,
                      player_required, is_rate_limited, record_attempt,
                      get_client_ip)
from ml       import (calculate_score, get_rating, get_ml_insight,
                      train_models_async, get_training_status,
                      load_model_accuracy, POSITION_STATS)
from services import (get_player_stats, build_match_history,
                      get_top_performers, next_player_id,
                      get_player_condition, get_all_player_stats_for_compare,
                      get_best_eleven, get_coach_dashboard_data)


# ── App factory ───────────────────────────────────────────────────────────────

def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['MODELS_FOLDER'], exist_ok=True)

    csrf = CSRFProtect(app)
    setup_logger(app)
    init_db(app)

    app.teardown_appcontext(close_db)

    return app, csrf


app, csrf = create_app()
TEAM_NAME = app.config['TEAM_NAME']


# ── Input sanitisation helpers ────────────────────────────────────────────────

def safe_int(val, default=0, lo=0, hi=9999):
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return default


def safe_float(val, default=0.0, lo=0.0, hi=100.0):
    try:
        return max(lo, min(hi, float(val)))
    except (TypeError, ValueError):
        return default


# ── Role helper ───────────────────────────────────────────────────────────────

def _dashboard_redirect():
    """Redirect to the correct dashboard for the current session role."""
    role = session.get('role')
    if role == 'admin':  return redirect(url_for('admin_dashboard'))
    if role == 'coach':  return redirect(url_for('coach_dashboard'))
    if role == 'player': return redirect(url_for('player_dashboard'))
    return redirect(url_for('login'))


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return _dashboard_redirect()


# FIX #2: @csrf.exempt on the view function directly — CSRFProtect.exempt()
# requires a function reference, not a string. Placing it here ensures the
# exemption is registered against the actual callable.
@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt   # login creates the session — no CSRF token exists yet
def login():
    if 'username' in session:
        session.clear()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        ip       = get_client_ip()

        if not username or not password:
            flash('Please enter both username and password.', 'danger')
            return render_template('login.html')

        if is_rate_limited(username, ip):
            app.logger.warning('Rate limited login: user=%s ip=%s', username, ip)
            flash(
                f'Too many failed attempts. Please wait '
                f'{app.config["LOGIN_LOCKOUT_MINUTES"]} minutes before trying again.',
                'danger'
            )
            return render_template('login.html')

        db   = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

        if user and check_password_hash(user['password'], password):
            record_attempt(username, ip, success=True)
            session.clear()
            session['username']  = username
            session['role']      = user['role']
            session['player_id'] = user['player_id'] or ''
            app.logger.info('Login success: user=%s role=%s ip=%s', username, user['role'], ip)
            flash('Welcome back!', 'success')
            return redirect(url_for('index'))
        else:
            record_attempt(username, ip, success=False)
            app.logger.warning('Login failed: user=%s ip=%s', username, ip)
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')


@app.route('/logout', methods=['GET', 'POST'])
@csrf.exempt   # logout only clears the session — no data is modified
def logout():
    user = session.get('username', 'unknown')
    session.clear()
    app.logger.info('Logout: user=%s', user)
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))


# ── Player dashboard ──────────────────────────────────────────────────────────

@app.route('/player_dashboard')
@player_required
def player_dashboard():
    player_id = session['player_id']
    stats     = get_player_stats(player_id)

    db      = get_db()
    player  = db.execute("SELECT * FROM players WHERE player_id=?", (player_id,)).fetchone()
    history_rows = db.execute(
        "SELECT * FROM performances WHERE player_id=? ORDER BY match_date DESC",
        (player_id,)
    ).fetchall()

    page     = request.args.get('page', 1, type=int)
    per_page = app.config['MATCHES_PER_PAGE']
    total    = len(history_rows)
    start    = (page - 1) * per_page
    paginated = history_rows[start: start + per_page]

    match_history = build_match_history(paginated, player['position']) if player else []

    return render_template('player_dashboard.html',
                           stats=stats,
                           player_id=player_id,
                           match_history=match_history,
                           page=page,
                           total_pages=(total + per_page - 1) // per_page,
                           team_name=TEAM_NAME)


# ── Coach dashboard ───────────────────────────────────────────────────────────

# FIX: Replaced @coach_required with a manual role check that allows both
# 'coach' AND 'admin' roles. Previously an admin visiting /coach_dashboard
# (e.g. after a delete_performance redirect) was blocked with an Access Denied
# error because their session role is 'admin', not 'coach'.
@app.route('/coach_dashboard')
@login_required()
def coach_dashboard():
    role = session.get('role')
    if role not in ('coach', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    pos_filter       = request.args.get('position', 'All')
    formation        = request.args.get('formation', '4-3-3')
    active_tab       = request.args.get('tab', 'squad')
    valid_formations = ['4-3-3', '4-4-2', '3-5-2', '4-2-3-1']
    if formation not in valid_formations:
        formation = '4-3-3'

    all_stats, top_performers, compare_stats, eleven = get_coach_dashboard_data(
        pos_filter=pos_filter, formation=formation
    )

    by_pos = {}
    for p in compare_stats:
        by_pos.setdefault(p['position'], []).append(p)

    return render_template('coach_dashboard.html',
                           players=all_stats,
                           top_performers=top_performers,
                           pos_filter=pos_filter,
                           active_tab=active_tab,
                           formation=formation,
                           valid_formations=valid_formations,
                           by_pos=by_pos,
                           eleven=eleven,
                           all_stats_json=json.dumps(compare_stats),
                           team_name=TEAM_NAME)


# ── Admin dashboard ───────────────────────────────────────────────────────────

@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    db      = get_db()
    players = [dict(r) for r in db.execute("SELECT * FROM players").fetchall()]
    users   = [dict(r) for r in db.execute("SELECT * FROM users").fetchall()]
    t_status = get_training_status()

    return render_template('admin_dashboard.html',
                           players=players,
                           users=users,
                           model_accuracy=load_model_accuracy(),
                           training_running=t_status['running'],
                           team_name=TEAM_NAME)


# ── Performance CRUD ──────────────────────────────────────────────────────────

# FIX: add_performance and edit_performance are accessible to both coach and
# admin (same role guard as coach_dashboard above).
@app.route('/add_performance', methods=['GET', 'POST'])
@login_required()
def add_performance():
    role = session.get('role')
    if role not in ('coach', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    db = get_db()
    if request.method == 'POST':
        player_id  = request.form.get('player_id', '').strip()
        match_date = request.form.get('match_date', '').strip()
        if not player_id or not match_date:
            flash('Player and match date are required.', 'danger')
        else:
            db.execute(
                '''INSERT INTO performances
                   (player_id,match_date,minutes_played,goals,assists,
                    shots_on_target,pass_accuracy,tackles,saves,clean_sheet)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (player_id, match_date,
                 safe_int(request.form.get('minutes_played', 0), 0, 0, 120),
                 safe_int(request.form.get('goals', 0),          0, 0, 20),
                 safe_int(request.form.get('assists', 0),         0, 0, 20),
                 safe_int(request.form.get('shots_on_target', 0), 0, 0, 50),
                 safe_float(request.form.get('pass_accuracy', 0), 0.0, 0.0, 100.0),
                 safe_int(request.form.get('tackles', 0),         0, 0, 50),
                 safe_int(request.form.get('saves', 0),           0, 0, 50),
                 1 if request.form.get('clean_sheet') == 'on' else 0)
            )
            db.commit()
            app.logger.info('Performance added: player=%s date=%s by=%s',
                            player_id, match_date, session['username'])
            flash('Performance data added successfully!', 'success')
            # FIX: redirect back to wherever the user came from (admin or coach)
            return _dashboard_redirect()

    players = [dict(r) for r in db.execute("SELECT * FROM players").fetchall()]
    return render_template('add_performance.html', players=players, team_name=TEAM_NAME)


@app.route('/edit_performance/<int:perf_id>', methods=['GET', 'POST'])
@login_required()
def edit_performance(perf_id):
    role = session.get('role')
    if role not in ('coach', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    db   = get_db()
    perf = db.execute("SELECT * FROM performances WHERE id=?", (perf_id,)).fetchone()
    if not perf:
        flash('Record not found.', 'danger')
        return _dashboard_redirect()

    if request.method == 'POST':
        db.execute(
            '''UPDATE performances SET
               match_date=?,minutes_played=?,goals=?,assists=?,shots_on_target=?,
               pass_accuracy=?,tackles=?,saves=?,clean_sheet=? WHERE id=?''',
            (request.form.get('match_date', perf['match_date']),
             safe_int(request.form.get('minutes_played', 0), 0, 0, 120),
             safe_int(request.form.get('goals', 0),          0, 0, 20),
             safe_int(request.form.get('assists', 0),         0, 0, 20),
             safe_int(request.form.get('shots_on_target', 0), 0, 0, 50),
             safe_float(request.form.get('pass_accuracy', 0), 0.0, 0.0, 100.0),
             safe_int(request.form.get('tackles', 0),         0, 0, 50),
             safe_int(request.form.get('saves', 0),           0, 0, 50),
             1 if request.form.get('clean_sheet') == 'on' else 0,
             perf_id)
        )
        db.commit()
        app.logger.info('Performance edited: id=%d by=%s', perf_id, session['username'])
        flash('Performance record updated!', 'success')
        # FIX: redirect back to wherever the user came from (admin or coach)
        return _dashboard_redirect()

    players = [dict(r) for r in db.execute("SELECT * FROM players").fetchall()]
    return render_template('edit_performance.html',
                           perf=dict(perf), players=players, team_name=TEAM_NAME)


@app.route('/delete_performance/<int:perf_id>', methods=['POST'])
@login_required()
def delete_performance(perf_id):
    role = session.get('role')
    if role not in ('coach', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    db = get_db()
    db.execute("DELETE FROM performances WHERE id=?", (perf_id,))
    db.commit()
    app.logger.info('Performance deleted: id=%d by=%s', perf_id, session['username'])
    flash('Performance record deleted!', 'success')
    # FIX: redirect back to wherever the user came from (admin or coach)
    return _dashboard_redirect()


# ── Admin: player management ──────────────────────────────────────────────────

@app.route('/add_player', methods=['POST'])
@admin_required
def add_player():
    db       = get_db()
    name     = request.form.get('name', '').strip()
    position = request.form.get('position', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    if not all([name, position, username, password]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if position not in POSITION_STATS:
        flash('Invalid position selected.', 'danger')
        return redirect(url_for('admin_dashboard'))

    age    = safe_int(request.form.get('age', 20), 20, 16, 45)
    new_id = next_player_id()

    try:
        db.execute("INSERT INTO players VALUES (?,?,?,?,?)",
                   (new_id, name, position, age, TEAM_NAME))
        db.execute(
            "INSERT INTO users (username,password,role,player_id) VALUES (?,?,?,?)",
            (username, generate_password_hash(password), 'player', new_id)
        )
        db.commit()
        app.logger.info('Player added: id=%s name=%s by=%s', new_id, name, session['username'])
        flash(f'Player {name} added with ID {new_id}!', 'success')
    except sqlite3.IntegrityError:
        flash('Error: Username already exists.', 'danger')

    return redirect(url_for('admin_dashboard'))


@app.route('/delete_player/<player_id>', methods=['POST'])
@admin_required
def delete_player(player_id):
    db = get_db()
    current_user = db.execute(
        "SELECT player_id FROM users WHERE username=?", (session['username'],)
    ).fetchone()
    if current_user and current_user['player_id'] == player_id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin_dashboard'))
    target_user = db.execute(
        "SELECT role FROM users WHERE player_id=?", (player_id,)
    ).fetchone()
    if target_user and target_user['role'] == 'admin':
        admin_count = db.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin'"
        ).fetchone()[0]
        if admin_count <= 1:
            flash('Cannot delete the last admin account.', 'danger')
            return redirect(url_for('admin_dashboard'))
    try:
        # ON DELETE CASCADE handles child rows when PRAGMA foreign_keys=ON (see get_db).
        # Manual deletes kept as a safety net for direct DB access outside the app.
        db.execute("DELETE FROM performances WHERE player_id=?", (player_id,))
        db.execute("DELETE FROM users WHERE player_id=?",        (player_id,))
        db.execute("DELETE FROM players WHERE player_id=?",      (player_id,))
        db.commit()
        app.logger.info('Player deleted: id=%s by=%s', player_id, session['username'])
        flash('Player deleted successfully!', 'success')
    except Exception as e:
        db.rollback()
        app.logger.error('Failed to delete player %s: %s', player_id, e)
        flash('Failed to delete player. Please try again.', 'danger')
    return redirect(url_for('admin_dashboard'))


# ── ML training (async) ───────────────────────────────────────────────────────

@app.route('/train_model', methods=['GET', 'POST'])
@admin_required
def train_model():
    db = get_db()
    if request.method == 'GET':
        count = db.execute("SELECT COUNT(*) FROM performances").fetchone()[0]
        return render_template('confirm_train.html',
                               perf_count=count, team_name=TEAM_NAME)

    players_data    = [dict(r) for r in db.execute("SELECT * FROM players").fetchall()]
    perfs_by_player = {}
    for p in players_data:
        rows = db.execute(
            "SELECT * FROM performances WHERE player_id=? ORDER BY match_date ASC",
            (p['player_id'],)
        ).fetchall()
        perfs_by_player[p['player_id']] = [dict(r) for r in rows]

    started = train_models_async(players_data, perfs_by_player, app.logger)
    if started:
        app.logger.info('Model training started by %s', session['username'])
        flash('Model training started in the background — refresh in ~30 seconds.', 'info')
    else:
        flash('Training is already running. Please wait.', 'warning')

    return redirect(url_for('admin_dashboard'))


@app.route('/api/training_status')
@admin_required
def api_training_status():
    """Poll this from the admin dashboard to check if training finished."""
    status = get_training_status()
    return jsonify({
        'running':  status['running'],
        'result':   status['result'],
        'accuracy': load_model_accuracy(),
    })


# ── API (authenticated) ───────────────────────────────────────────────────────

@app.route('/api/player_performance/<player_id>')
@login_required()
def api_player_performance(player_id):
    """
    Return chart data for a player.
    Players can only access their own data; coaches/admins can access any.
    """
    role = session.get('role')
    if role == 'player' and session.get('player_id') != player_id:
        return jsonify({'error': 'Access denied'}), 403

    db = get_db()

    # FIX #7: return 404 if the player doesn't exist instead of silently
    # returning empty chart data with a misleading 200 status.
    player_row = db.execute(
        "SELECT player_id FROM players WHERE player_id=?", (player_id,)
    ).fetchone()
    if not player_row:
        return jsonify({'error': 'Player not found'}), 404

    perfs = db.execute(
        """SELECT p.*, pl.position
           FROM performances p
           JOIN players pl ON p.player_id = pl.player_id
           WHERE p.player_id=? ORDER BY match_date ASC""",
        (player_id,)
    ).fetchall()

    if not perfs:
        return jsonify({'labels': [], 'scores': [], 'goals': [], 'pass_accuracy': []})

    labels, scores, goals, pass_acc = [], [], [], []
    for i, p in enumerate(perfs):
        labels.append(f'Match {i+1}')
        scores.append(calculate_score(dict(p), p['position']))
        goals.append(p['goals'])
        pass_acc.append(p['pass_accuracy'])

    return jsonify({'labels': labels, 'scores': scores,
                    'goals': goals, 'pass_accuracy': pass_acc})


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(CSRFError)
def csrf_error(e):
    app.logger.warning('CSRF error: %s — path=%s', e.description, request.path)
    flash('Your session expired. Please try again.', 'warning')
    return redirect(url_for('login'))


@app.errorhandler(403)
def forbidden(e):
    return render_template('login.html',
                           error_message='Access denied.'), 403


@app.errorhandler(404)
def not_found(e):
    flash('Page not found.', 'warning')
    return redirect(url_for('index'))


@app.errorhandler(405)
def method_not_allowed(e):
    app.logger.warning('405 Method Not Allowed: %s %s', request.method, request.path)
    flash('Invalid request method.', 'danger')
    return redirect(url_for('index'))


@app.errorhandler(500)
def server_error(e):
    app.logger.error('500 error: %s', e, exc_info=True)
    flash('An unexpected error occurred. Please try again.', 'danger')
    return redirect(url_for('index'))


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    debug = os.environ.get('FLASK_ENV', 'development') == 'development'
    app.run(debug=debug, host='0.0.0.0', port=5000)