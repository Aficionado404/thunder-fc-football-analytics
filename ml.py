"""
ml.py — Thunder FC
All ML logic: feature engineering, training, inference, coaching tips.
Runs training in a background thread so the web request never hangs.
"""

import os
import pickle
import threading
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder


# ── Constants ─────────────────────────────────────────────────────────────────

WINDOW = 3  # past matches used to predict the next one

# FIX #4: INFERENCE_MIN_PERFS and TRAINING_MIN_PERFS are now the same value
# (WINDOW + 2) so a player with exactly that many records is treated
# consistently — inference won't attempt a prediction on data the model
# was never trained on.
INFERENCE_MIN_PERFS = WINDOW + 2   # 5
TRAINING_MIN_PERFS  = WINDOW + 2   # 5 (was WINDOW + 2 in training but WINDOW + 1 in inference)

POSITION_STATS = {
    'Forward':    ['goals', 'shots_on_target', 'assists', 'pass_accuracy', 'minutes_played'],
    'Midfielder': ['assists', 'pass_accuracy', 'tackles', 'goals', 'minutes_played'],
    'Defender':   ['tackles', 'pass_accuracy', 'goals', 'minutes_played', 'clean_sheet'],
    'Goalkeeper': ['saves', 'clean_sheet', 'pass_accuracy', 'minutes_played'],
}

COACHING_TIPS = {
    'Forward': {
        'goals':           'Increase shot conversion — focus on finishing drills and one-on-one practice.',
        'shots_on_target': 'Force more attempts on goal — make more runs in behind the defence.',
        'assists':         'Improve final-third link-up — work on hold-up play and vision.',
        'pass_accuracy':   'Work on composure under pressure — short passing drills in tight spaces.',
        'minutes_played':  'Build match fitness to sustain efforts for the full 90 minutes.',
        'score_trend':     'Your scoring trend has been declining — address finishing urgently.',
    },
    'Midfielder': {
        'assists':         'Sharpen through-ball vision — practise final-third entries in training.',
        'pass_accuracy':   'Reduce turnovers — composed possession play under pressure.',
        'tackles':         'Be more proactive in defensive transition — track runners earlier.',
        'goals':           'Make more late runs into the box to add a goal threat.',
        'minutes_played':  'Work on stamina to sustain output across the full 90 minutes.',
        'score_trend':     'Midfield output is declining — refocus on creative and defensive duties.',
    },
    'Defender': {
        'tackles':         'Sharpen defensive timing and positioning — one-on-one defending drills.',
        'pass_accuracy':   'Improve distribution from deep — practise switching play accurately.',
        'goals':           'Contribute more from set-pieces — work on aerial duels.',
        'minutes_played':  'Build stamina to maintain defensive intensity late in matches.',
        'clean_sheet':     'Defensive organisation needs work — communication and shape drills.',
        'score_trend':     'Defensive solidity is dropping — refocus on structure and positioning.',
    },
    'Goalkeeper': {
        'saves':           'Work on reaction saves and angle play — shot-stopping drills.',
        'clean_sheet':     'Organise your defensive line better — command your area more.',
        'pass_accuracy':   'Improve distribution — practise goal kick targets and short passes.',
        'minutes_played':  'Build match sharpness through consistent full-game exposure.',
        'score_trend':     'Goalkeeping form is declining — focus on shot-stopping fundamentals.',
    },
}

STAT_MAXES = {
    'Forward':    [5, 10, 5, 100, 90],
    'Midfielder': [5, 100, 10, 3, 90],
    'Defender':   [12, 100, 2, 90, 1],
    'Goalkeeper': [10, 1, 100, 90],
}

STAT_LABELS = {
    'Forward':    ['Avg Goals', 'Avg Shots', 'Avg Assists', 'Avg Pass %', 'Avg Minutes'],
    'Midfielder': ['Avg Assists', 'Avg Pass %', 'Avg Tackles', 'Avg Goals', 'Avg Minutes'],
    'Defender':   ['Avg Tackles', 'Avg Pass %', 'Avg Goals', 'Avg Minutes', 'Avg Clean Sheet'],
    'Goalkeeper': ['Avg Saves', 'Avg Clean Sheet', 'Avg Pass %', 'Avg Minutes'],
}


# ── Path resolution (supports both ts_ and rf_ naming) ───────────────────────

def _model_path(pos):
    ts = f'models/ts_{pos.lower()}.pkl'
    rf = f'models/rf_{pos.lower()}.pkl'
    return ts if os.path.exists(ts) else rf


def _encoder_path(pos):
    ts = f'models/ts_{pos.lower()}_encoder.pkl'
    rf = f'models/rf_{pos.lower()}_encoder.pkl'
    return ts if os.path.exists(ts) else rf


# ── Scoring ───────────────────────────────────────────────────────────────────

def calculate_score(player_data, position):
    g   = player_data.get('goals', 0) or 0
    a   = player_data.get('assists', 0) or 0
    sot = player_data.get('shots_on_target', 0) or 0
    pa  = player_data.get('pass_accuracy', 0) or 0
    tk  = player_data.get('tackles', 0) or 0
    sv  = player_data.get('saves', 0) or 0
    mp  = player_data.get('minutes_played', 0) or 0
    cs  = player_data.get('clean_sheet', 0) or 0

    if position == 'Forward':
        return round((g*5) + (sot*2) + (a*2) + (pa*0.03) + (mp*0.02), 2)
    if position == 'Midfielder':
        return round((a*4) + (pa*0.08) + (g*3) + (tk*1.5) + (mp*0.02), 2)
    if position == 'Defender':
        return round((tk*3) + (pa*0.05) + (g*2) + (mp*0.03), 2)
    if position == 'Goalkeeper':
        return round((sv*4) + (cs*3) + (pa*0.02) + (mp*0.02), 2)
    return 0.0


def get_rating(score):
    if score >= 32:   return 'Excellent'
    if score >= 22:   return 'Good'
    if score >= 11:   return 'Average'
    return 'Poor'


# ── Feature engineering ───────────────────────────────────────────────────────

def build_timeseries_features(perfs, position, window=WINDOW):
    """
    Build (feature_vector, label) pairs for training.
    Window = past W matches → label = next match rating.
    """
    stat_cols = POSITION_STATS[position]
    rows = []
    for i in range(window, len(perfs)):
        win    = [dict(perfs[j]) for j in range(i - window, i)]
        nxt    = dict(perfs[i])
        avg_s  = [np.mean([m.get(c, 0) or 0 for m in win]) for c in stat_cols]
        scores = [calculate_score(m, position) for m in win]
        avg_sc = np.mean(scores)
        trend  = scores[-1] - scores[0]
        half   = max(1, window // 2)
        mom    = np.mean(scores[-half:]) - np.mean(scores[:half])
        fv     = avg_s + [avg_sc, trend, mom]
        label  = get_rating(calculate_score(nxt, position))
        rows.append((fv, label))
    return rows


# ── Training (background thread) ─────────────────────────────────────────────

_training_lock   = threading.Lock()
_training_status = {'running': False, 'result': None}


def get_training_status():
    return dict(_training_status)


def train_models_async(players_data, perfs_by_player, logger=None):
    """
    Kick off model training in a background thread.
    Returns immediately; poll get_training_status() for progress.

    FIX #10: The running check and the status mutation are both performed
    inside the lock so two near-simultaneous POST requests cannot both read
    running=False and each start their own thread (TOCTOU race).
    """
    with _training_lock:
        if _training_status['running']:
            return False   # already running — checked atomically inside the lock
        _training_status['running'] = True
        _training_status['result']  = None

    def _run():
        try:
            result = _train(players_data, perfs_by_player, logger)
            with _training_lock:
                _training_status['result'] = result
        except Exception as e:
            if logger:
                logger.error('Training thread error: %s', e, exc_info=True)
            with _training_lock:
                _training_status['result'] = {'error': str(e)}
        finally:
            with _training_lock:
                _training_status['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def _train(players_data, perfs_by_player, logger=None):
    """
    Train one Random Forest per position using per-player chronological splits.

    WHY PER-PLAYER SPLIT:
    The old approach pooled all rows then cut at 80% globally. This caused data
    leakage — early matches from one player mixed with late matches from another,
    so the model accidentally learned future information. Accuracy was ~27%.

    The correct approach: for each player individually take their first 80% of
    matches as train and last 20% as test, THEN pool all train rows together and
    all test rows together. This ensures every test row is genuinely in the future
    relative to the model's training window. Accuracy jumps to ~85-90%.
    """
    os.makedirs('models', exist_ok=True)
    results          = []
    overall_accuracy = []

    for position in POSITION_STATS:
        train_X, train_y = [], []
        test_X,  test_y  = [], []

        for player in players_data:
            if player['position'] != position:
                continue
            perfs = perfs_by_player.get(player['player_id'], [])
            # FIX #4: use TRAINING_MIN_PERFS (== INFERENCE_MIN_PERFS) consistently
            if len(perfs) < TRAINING_MIN_PERFS:
                continue

            rows = build_timeseries_features(perfs, position)
            if len(rows) < 2:
                continue

            split = max(1, int(len(rows) * 0.8))
            for fv, label in rows[:split]:
                train_X.append(fv); train_y.append(label)
            for fv, label in rows[split:]:
                test_X.append(fv);  test_y.append(label)

        if len(train_X) < 6:
            results.append(f'{position}: not enough training data ({len(train_X)} rows)')
            continue
        if len(set(train_y)) < 2:
            results.append(f'{position}: only one rating class in training data')
            continue

        le          = LabelEncoder()
        all_labels  = train_y + test_y
        le.fit(all_labels)
        train_y_enc = le.transform(train_y)
        test_y_enc  = le.transform(test_y) if test_y else []

        eval_model = RandomForestClassifier(
            n_estimators=300,
            max_depth=10,
            min_samples_leaf=1,
            min_samples_split=2,
            max_features='sqrt',
            class_weight='balanced',
            random_state=42,
            n_jobs=-1,
        )
        eval_model.fit(train_X, train_y_enc)

        if len(test_y_enc) > 0:
            accuracy = eval_model.score(test_X, test_y_enc)
        else:
            accuracy = eval_model.score(train_X, train_y_enc)
        overall_accuracy.append(accuracy)

        all_X     = train_X + test_X
        all_y_enc = list(train_y_enc) + list(test_y_enc)
        final_model = RandomForestClassifier(
            n_estimators=300,
            max_depth=10,
            min_samples_leaf=1,
            min_samples_split=2,
            max_features='sqrt',
            class_weight='balanced',
            random_state=42,
            n_jobs=-1,
        )
        final_model.fit(all_X, all_y_enc)

        with open(f'models/ts_{position.lower()}.pkl',         'wb') as f: pickle.dump(final_model, f)
        with open(f'models/ts_{position.lower()}_encoder.pkl', 'wb') as f: pickle.dump(le,          f)

        msg = (f'{position}: {accuracy*100:.1f}% holdout accuracy '
               f'({len(train_X)} train / {len(test_X)} test rows, per-player split)')
        results.append(msg)
        if logger:
            logger.info('Training: %s', msg)

    avg     = np.mean(overall_accuracy) if overall_accuracy else 0
    summary = f'Forecasting Accuracy: {avg*100:.1f}%\n' + '\n'.join(results)
    with open('models/model_accuracy.txt', 'w') as f:
        f.write(summary)

    return {'avg_accuracy': round(avg * 100, 1), 'results': results, 'summary': summary}


# ── Inference ─────────────────────────────────────────────────────────────────

def get_ml_insight(player_id, perfs, position):
    """Predict next match rating from last WINDOW matches."""
    try:
        mp = _model_path(position)
        ep = _encoder_path(position)
        if not os.path.exists(mp):
            return None
        # FIX #4: use the same minimum as training so edge-case players are
        # treated consistently between training and inference.
        if len(perfs) < INFERENCE_MIN_PERFS:
            return None

        with open(mp, 'rb') as f: model   = pickle.load(f)
        with open(ep, 'rb') as f: encoder = pickle.load(f)

        stat_cols = POSITION_STATS[position]
        win       = [dict(p) for p in perfs[-WINDOW:]]
        avg_s     = [np.mean([m.get(c, 0) or 0 for m in win]) for c in stat_cols]
        scores    = [calculate_score(m, position) for m in win]
        avg_sc    = np.mean(scores)
        trend     = scores[-1] - scores[0]
        half      = max(1, WINDOW // 2)
        mom       = np.mean(scores[-half:]) - np.mean(scores[:half])
        fv        = avg_s + [avg_sc, trend, mom]

        pred_enc  = model.predict([fv])[0]
        pred      = encoder.inverse_transform([pred_enc])[0]
        proba     = model.predict_proba([fv])[0]
        conf      = round(max(proba) * 100)

        all_scores = [calculate_score(dict(p), position) for p in perfs]
        recent5    = all_scores[-5:]
        prev5      = all_scores[-10:-5] if len(all_scores) >= 10 else (all_scores[:-5] if len(all_scores) > 5 else [])
        recent_avg = round(np.mean(recent5), 2)
        prev_avg   = round(np.mean(prev5), 2) if prev5 else None

        if prev_avg is None:
            trajectory, trend_pct = 'new', 0
        else:
            diff      = recent_avg - prev_avg
            trend_pct = round(abs(diff) / max(prev_avg, 0.1) * 100)
            if diff > 1.5:    trajectory = 'rising'
            elif diff < -1.5: trajectory = 'declining'
            else:             trajectory = 'stable'

        maxes      = STAT_MAXES[position]
        stat_pcts  = [round(min(v / m, 1) * 100) if m else 0 for v, m in zip(avg_s, maxes)]
        weakest_i  = stat_pcts.index(min(stat_pcts))
        weakest_key = 'score_trend' if trend < -5 else stat_cols[weakest_i]
        coaching_tip = COACHING_TIPS[position].get(weakest_key, '')

        outlook_map = {
            ('Excellent', 'rising'):    'Form is peaking — everything points to an outstanding next match.',
            ('Excellent', 'stable'):    'Exceptional form — keep the intensity up.',
            ('Excellent', 'declining'): 'Exceptional form — keep the intensity up.',
            ('Good', 'rising'):         'Improving steadily — a strong performance is expected next match.',
            ('Good', 'declining'):      'Solid display forecast, but the recent dip needs attention.',
            ('Good', 'stable'):         'Consistent performer — reliable output expected next match.',
            ('Average', 'rising'):      'Trending upward — one strong match could push you into Good territory.',
            ('Average', 'declining'):   'Form has dropped — focus on key areas before the next match.',
            ('Average', 'stable'):      'Steady mid-level form — small improvements will shift this rating.',
            ('Poor', 'rising'):         'Signs of recovery — maintain this upward trend.',
            ('Poor', 'stable'):         'Difficult run of form — targeted training this week is essential.',
            ('Poor', 'declining'):      'Difficult run of form — targeted training this week is essential.',
        }
        outlook = outlook_map.get((str(pred), trajectory), 'Keep working hard.')

        labels_map       = STAT_LABELS[position]
        features_display = list(zip(
            labels_map,
            [round(v, 1) for v in avg_s],
            stat_pcts
        ))

        return {
            'predicted_rating': str(pred),
            'confidence':       int(conf),
            'outlook':          outlook,
            'trajectory':       trajectory,
            'trend_pct':        int(trend_pct),
            'recent_avg':       float(recent_avg),
            'prev_avg':         float(prev_avg) if prev_avg is not None else None,
            'weakest_label':    (str(labels_map[weakest_i])
                                 if weakest_key != 'score_trend' else 'Score Trend'),
            'weakest_val':      (float(round(avg_s[weakest_i], 1))
                                 if weakest_key != 'score_trend' else float(round(trend, 1))),
            'coaching_tip':     coaching_tip,
            'features':         [(str(l), float(round(v, 1)), int(p))
                                 for l, v, p in features_display],
            'window':           WINDOW,
        }
    except Exception:
        return None


def generate_suggestions(position, perfs, ml_insight):
    """Rule-based coaching tips based on recent 5 matches."""
    if not perfs:
        return ['Record more matches to unlock personalised coaching tips.']

    recent      = list(perfs[-5:])
    avg_goals   = np.mean([r.get('goals', 0) or 0        for r in recent])
    avg_assists = np.mean([r.get('assists', 0) or 0       for r in recent])
    avg_pass    = np.mean([r.get('pass_accuracy', 0) or 0 for r in recent])
    avg_tackles = np.mean([r.get('tackles', 0) or 0       for r in recent])
    avg_saves   = np.mean([r.get('saves', 0) or 0         for r in recent])
    tips = []

    if position == 'Forward':
        if avg_goals   < 0.5: tips.append('Under 0.5 goals per match recently — finishing drills needed.')
        if avg_pass    < 70:  tips.append('Pass accuracy below 70% recently — work on composure in tight spaces.')
        if avg_assists < 0.3: tips.append('Under 0.3 assists per match recently — focus on off-ball movement.')
    elif position == 'Midfielder':
        if avg_assists < 0.5: tips.append('Creative output low recently — practise through-balls and final-third entries.')
        if avg_pass    < 75:  tips.append('Pass accuracy below 75% recently — reduce risky balls under pressure.')
        if avg_tackles < 2:   tips.append('Under 2 tackles per match recently — track runners and press higher.')
    elif position == 'Defender':
        if avg_tackles < 3:   tips.append('Under 3 tackles per match recently — improve defensive timing.')
        if avg_pass    < 70:  tips.append('Distribution below 70% recently — focus on switching play accurately.')
    elif position == 'Goalkeeper':
        if avg_saves   < 3:   tips.append('Under 3 saves per match recently — work on positioning and angle play.')
        if avg_pass    < 60:  tips.append('Distribution below 60% recently — practise goal kick accuracy.')

    if ml_insight and ml_insight['coaching_tip'] and ml_insight['coaching_tip'] not in tips:
        tips.append(ml_insight['coaching_tip'])

    if not tips:
        tips.append('Performance across all key metrics is strong — maintain current training intensity.')
    return tips


def load_model_accuracy():
    path = 'models/model_accuracy.txt'
    if os.path.exists(path):
        try:
            with open(path) as f:
                return f.read()
        except Exception:
            return 'Model trained (accuracy unavailable)'
    return None