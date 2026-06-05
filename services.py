"""
services.py — Thunder FC
Business logic layer — player stats aggregation, conditions, top performers.
Keeps routes thin and testable.

OPTIMISATION (was 203 DB queries per coach dashboard load → now 4):
  All per-player loops have been replaced with two bulk queries:
    1. SELECT * FROM players
    2. SELECT * FROM performances   (all players at once)
  Everything else is pure Python grouping/aggregation in memory.
"""

import numpy as np
from db import get_db
from ml import calculate_score, get_rating, get_ml_insight, generate_suggestions


# ── Internal bulk loader ───────────────────────────────────────────────────────

def _load_all_data():
    """
    Two queries fetch everything needed by every function on this page.
    Returns (players_by_id, perfs_by_player).
    """
    db = get_db()

    players = db.execute("SELECT * FROM players").fetchall()
    players_by_id = {p['player_id']: dict(p) for p in players}

    perfs = db.execute(
        "SELECT * FROM performances ORDER BY player_id, match_date ASC"
    ).fetchall()
    perfs_by_player = {}
    for row in perfs:
        pid = row['player_id']
        perfs_by_player.setdefault(pid, []).append(dict(row))

    return players_by_id, perfs_by_player


# ── Condition helper (works from pre-loaded data) ─────────────────────────────

def _condition_from_perfs(perfs_asc, position):
    """Compute condition label + colour from the last 5 performances."""
    if not perfs_asc:
        return 'N/A', 'gray'
    recent = perfs_asc[-5:]
    scores = [calculate_score(p, position) for p in recent]
    avg    = np.mean(scores)
    if avg >= 32: return 'Excellent', 'green'
    if avg >= 22: return 'Good',      'blue'
    if avg >= 11: return 'Average',   'orange'
    return 'Poor', 'red'


# ── Public single-player helpers (used by player dashboard) ───────────────────

def get_player_condition(player_id):
    """Single-player condition — still used by player_dashboard."""
    db     = get_db()
    rows   = db.execute(
        "SELECT * FROM performances WHERE player_id=? ORDER BY match_date DESC LIMIT 5",
        (player_id,)
    ).fetchall()
    player = db.execute("SELECT * FROM players WHERE player_id=?", (player_id,)).fetchone()
    if not rows or not player:
        return 'N/A', 'gray'
    scores = [calculate_score(dict(r), player['position']) for r in rows]
    avg    = np.mean(scores)
    if avg >= 32:   return 'Excellent', 'green'
    if avg >= 22:   return 'Good',      'blue'
    if avg >= 11:   return 'Average',   'orange'
    return 'Poor', 'red'


def get_player_stats(player_id):
    """Full stat block for one player including ML insight and suggestions."""
    db     = get_db()
    perfs  = db.execute(
        "SELECT * FROM performances WHERE player_id=? ORDER BY match_date ASC",
        (player_id,)
    ).fetchall()
    player = db.execute("SELECT * FROM players WHERE player_id=?", (player_id,)).fetchone()
    if not perfs or not player:
        return None

    pos               = player['position']
    perfs_list        = [dict(p) for p in perfs]
    scores            = [calculate_score(p, pos) for p in perfs_list]
    condition, ccolor = _condition_from_perfs(perfs_list, pos)
    ml_insight        = get_ml_insight(player_id, perfs, pos)
    suggestions       = generate_suggestions(pos, perfs_list, ml_insight)

    return {
        'name':                  player['name'],
        'position':              pos,
        'player_id':             player_id,
        'total_matches':         len(perfs),
        'total_goals':           sum(p['goals']   for p in perfs_list),
        'total_assists':         sum(p['assists']  for p in perfs_list),
        'avg_pass_accuracy':     round(np.mean([p['pass_accuracy'] for p in perfs_list]), 1),
        'total_tackles':         sum(p['tackles']  for p in perfs_list),
        'total_saves':           sum(p['saves']    for p in perfs_list) if pos == 'Goalkeeper' else 0,
        'avg_performance_score': round(np.mean(scores), 2),
        'performance_rating':    get_rating(np.mean(scores)),
        'condition':             condition,
        'condition_color':       ccolor,
        'suggestions':           suggestions,
        'ml_insight':            ml_insight,
    }


def build_match_history(history_rows, position):
    """Convert raw DB rows to a list of dicts with score + rating."""
    result = []
    for i, p in enumerate(history_rows):
        d = dict(p) if not isinstance(p, dict) else p
        score = calculate_score(d, position)
        result.append({
            'match_num':       len(history_rows) - i,
            'id':              d['id'],
            'match_date':      d['match_date'],
            'minutes_played':  d['minutes_played'],
            'goals':           d['goals'],
            'assists':         d['assists'],
            'shots_on_target': d['shots_on_target'],
            'pass_accuracy':   d['pass_accuracy'],
            'tackles':         d['tackles'],
            'saves':           d['saves'],
            'clean_sheet':     d['clean_sheet'],
            'score':           score,
            'rating':          get_rating(score),
        })
    return result


def next_player_id():
    """Auto-generate the next player ID (P021, P022 …)."""
    db  = get_db()
    row = db.execute(
        "SELECT player_id FROM players WHERE player_id LIKE 'P%' "
        "ORDER BY CAST(SUBSTR(player_id, 2) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    if row:
        try:
            return f"P{int(row['player_id'][1:]) + 1:03d}"
        except ValueError:
            pass
    return 'P001'


# ── Bulk functions — 2 queries total for all players ─────────────────────────

def get_coach_dashboard_data(pos_filter='All', formation='4-3-3'):
    """
    Single entry point for the coach dashboard.
    Fires exactly 2 DB queries regardless of squad size, then does all
    aggregation in Python.

    FIX #8: get_ml_insight() was called twice per player (once for the squad
    tab stat block, once for compare stats), each call loading the .pkl file
    from disk. Now it is called exactly once per player and the result is
    reused for both outputs.

    Returns:
        all_stats      — list of full stat dicts (squad tab)
        top_performers — best player per position
        compare_stats  — lightweight stats for compare/lineup tabs
        eleven         — best XI dict for the chosen formation
    """
    FORMATIONS = {
        '4-3-3':   {'Goalkeeper': 1, 'Defender': 4, 'Midfielder': 3, 'Forward': 3},
        '4-4-2':   {'Goalkeeper': 1, 'Defender': 4, 'Midfielder': 4, 'Forward': 2},
        '3-5-2':   {'Goalkeeper': 1, 'Defender': 3, 'Midfielder': 5, 'Forward': 2},
        '4-2-3-1': {'Goalkeeper': 1, 'Defender': 4, 'Midfielder': 5, 'Forward': 1},
    }

    players_by_id, perfs_by_player = _load_all_data()

    all_stats     = []
    compare_stats = []
    top           = {}

    for pid, player in players_by_id.items():
        pos   = player['position']
        perfs = perfs_by_player.get(pid, [])

        if not perfs:
            continue

        scores    = [calculate_score(p, pos) for p in perfs]
        avg_score = round(np.mean(scores), 2)
        condition, ccolor = _condition_from_perfs(perfs, pos)

        # FIX #8: compute ML insight exactly once per player and reuse below
        ml_insight = get_ml_insight(pid, perfs, pos)

        # ── Squad tab stat block ──────────────────────────────────────────────
        if pos_filter == 'All' or pos_filter == pos:
            suggestions = generate_suggestions(pos, perfs, ml_insight)
            history     = build_match_history(list(reversed(perfs)), pos)

            stat = {
                'name':                  player['name'],
                'position':              pos,
                'player_id':             pid,
                'total_matches':         len(perfs),
                'total_goals':           sum(p['goals']   for p in perfs),
                'total_assists':         sum(p['assists']  for p in perfs),
                'avg_pass_accuracy':     round(np.mean([p['pass_accuracy'] for p in perfs]), 1),
                'total_tackles':         sum(p['tackles']  for p in perfs),
                'total_saves':           sum(p['saves']    for p in perfs) if pos == 'Goalkeeper' else 0,
                'avg_performance_score': avg_score,
                'performance_rating':    get_rating(np.mean(scores)),
                'condition':             condition,
                'condition_color':       ccolor,
                'suggestions':           suggestions,
                'ml_insight':            ml_insight,   # reused — no second disk read
                'match_history':         history,
            }
            all_stats.append(stat)

        # ── Top performers ────────────────────────────────────────────────────
        if pos not in top or avg_score > top[pos]['score']:
            top[pos] = {
                'name':      player['name'],
                'player_id': pid,
                'score':     avg_score,
                'position':  pos,
            }

        # ── Compare / Best XI lightweight stats ───────────────────────────────
        recent10    = perfs[-10:]
        scores10    = [calculate_score(p, pos) for p in recent10]
        avg10       = round(np.mean(scores10), 2)
        recent_form = [get_rating(s) for s in scores10[:5]]

        compare_stats.append({
            'player_id':       pid,
            'name':            player['name'],
            'position':        pos,
            'age':             player['age'],
            'avg_score':       avg10,
            'recent_form':     recent_form,
            'total_goals':     sum(p['goals']   for p in perfs),
            'total_assists':   sum(p['assists']  for p in perfs),
            'avg_pass':        round(np.mean([p['pass_accuracy'] for p in perfs]), 1),
            'total_tackles':   sum(p['tackles']  for p in perfs),
            'total_saves':     sum(p['saves']    for p in perfs),
            'matches':         len(perfs),
            'condition':       condition,
            'condition_color': ccolor,
            'ml_rating':       ml_insight['predicted_rating'] if ml_insight else None,
            'ml_confidence':   ml_insight['confidence']       if ml_insight else None,
            'ml_trajectory':   ml_insight['trajectory']       if ml_insight else None,
        })

    top_performers = list(top.values())

    # ── Best XI ───────────────────────────────────────────────────────────────
    slots  = FORMATIONS.get(formation, FORMATIONS['4-3-3'])
    by_pos = {'Goalkeeper': [], 'Defender': [], 'Midfielder': [], 'Forward': []}
    for p in compare_stats:
        if p['position'] in by_pos:
            by_pos[p['position']].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x['avg_score'], reverse=True)

    starting = {}
    bench    = []
    for pos, count in slots.items():
        starting[pos] = by_pos[pos][:count]
        bench.extend(by_pos[pos][count:count + 2])
    bench.sort(key=lambda x: x['avg_score'], reverse=True)

    eleven = {
        'formation':   formation,
        'slots':       slots,
        'gk':          starting.get('Goalkeeper', []),
        'defenders':   starting.get('Defender',   []),
        'midfielders': starting.get('Midfielder',  []),
        'forwards':    starting.get('Forward',    []),
        'bench':       bench[:7],
        'all_by_pos':  by_pos,
    }

    return all_stats, top_performers, compare_stats, eleven


# ── Legacy wrappers — still used by player_dashboard and admin ────────────────

def get_top_performers():
    """Kept for admin dashboard — fires N+1 queries but only called once there."""
    db      = get_db()
    players = db.execute("SELECT * FROM players").fetchall()
    top     = {}
    for p in players:
        perfs = db.execute(
            "SELECT * FROM performances WHERE player_id=?", (p['player_id'],)
        ).fetchall()
        if not perfs:
            continue
        scores = [calculate_score(dict(r), p['position']) for r in perfs]
        avg    = round(np.mean(scores), 2)
        pos    = p['position']
        if pos not in top or avg > top[pos]['score']:
            top[pos] = {
                'name':      p['name'],
                'player_id': p['player_id'],
                'score':     avg,
                'position':  pos,
            }
    return list(top.values())


def get_all_player_stats_for_compare():
    """
    FIX #1: Removed the broken no-op lambda that assigned four Nones to
    throwaway variables without actually calling get_coach_dashboard_data.
    The function now goes directly to _load_all_data() as intended.
    """
    players_by_id, perfs_by_player = _load_all_data()
    result = []
    for pid, player in players_by_id.items():
        pos   = player['position']
        perfs = perfs_by_player.get(pid, [])
        if not perfs:
            continue
        recent10    = perfs[-10:]
        scores10    = [calculate_score(p, pos) for p in recent10]
        avg10       = round(np.mean(scores10), 2)
        recent_form = [get_rating(s) for s in scores10[:5]]
        condition, ccolor = _condition_from_perfs(perfs, pos)
        ml = get_ml_insight(pid, perfs, pos)
        result.append({
            'player_id':       pid,
            'name':            player['name'],
            'position':        pos,
            'age':             player['age'],
            'avg_score':       avg10,
            'recent_form':     recent_form,
            'total_goals':     sum(p['goals']   for p in perfs),
            'total_assists':   sum(p['assists']  for p in perfs),
            'avg_pass':        round(np.mean([p['pass_accuracy'] for p in perfs]), 1),
            'total_tackles':   sum(p['tackles']  for p in perfs),
            'total_saves':     sum(p['saves']    for p in perfs),
            'matches':         len(perfs),
            'condition':       condition,
            'condition_color': ccolor,
            'ml_rating':       ml['predicted_rating'] if ml else None,
            'ml_confidence':   ml['confidence']       if ml else None,
            'ml_trajectory':   ml['trajectory']       if ml else None,
        })
    return result


def get_best_eleven(formation='4-3-3'):
    """Legacy wrapper — coach dashboard uses get_coach_dashboard_data instead."""
    FORMATIONS = {
        '4-3-3':   {'Goalkeeper': 1, 'Defender': 4, 'Midfielder': 3, 'Forward': 3},
        '4-4-2':   {'Goalkeeper': 1, 'Defender': 4, 'Midfielder': 4, 'Forward': 2},
        '3-5-2':   {'Goalkeeper': 1, 'Defender': 3, 'Midfielder': 5, 'Forward': 2},
        '4-2-3-1': {'Goalkeeper': 1, 'Defender': 4, 'Midfielder': 5, 'Forward': 1},
    }
    slots     = FORMATIONS.get(formation, FORMATIONS['4-3-3'])
    all_stats = get_all_player_stats_for_compare()
    by_pos    = {'Goalkeeper': [], 'Defender': [], 'Midfielder': [], 'Forward': []}
    for p in all_stats:
        if p['position'] in by_pos:
            by_pos[p['position']].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x['avg_score'], reverse=True)
    starting = {}
    bench    = []
    for pos, count in slots.items():
        starting[pos] = by_pos[pos][:count]
        bench.extend(by_pos[pos][count:count + 2])
    bench.sort(key=lambda x: x['avg_score'], reverse=True)
    return {
        'formation':   formation,
        'slots':       slots,
        'gk':          starting.get('Goalkeeper', []),
        'defenders':   starting.get('Defender',   []),
        'midfielders': starting.get('Midfielder',  []),
        'forwards':    starting.get('Forward',    []),
        'bench':       bench[:7],
        'all_by_pos':  by_pos,
    }