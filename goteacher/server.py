"""Flask server: routes that tie the Game, KataGo engine, and Coach together."""

import os
import sys
import threading

try:
    from flask import Flask, Response, jsonify, render_template, request
except ImportError:
    print("Missing dependency: pip install flask")
    sys.exit(1)

from . import review
from .coach import Coach
from .config import (
    COACH_MODELS,
    DEFAULT_COACH_MODEL,
    KATAGO_EXE,
    MAIN_MODEL,
    MISTAKE_CONFIRM_VISITS,
    PORT,
)
from .engine import KataGo
from .rules import Game

app = Flask(__name__)
engine = None
coach = None
game = None
state_lock = threading.Lock()


def game_result():
    """Result string once the game is over, else None."""
    if not game.game_over:
        return None
    if game.result:
        return game.result
    if game.analysis_history:
        lead = game.analysis_history[-1]["rootInfo"].get("scoreLead", 0)
        winner = "B" if lead >= 0 else "W"
        return f"{winner}+{abs(lead):.1f} (estimate)"
    return None


def board_state(extra=None):
    root = game.analysis_history[-1]["rootInfo"] if game.analysis_history else {}
    d = {
        "size": game.size,
        "board": game.board,
        "to_move": game.to_move,
        "player_color": game.player_color,
        "moves": game.moves,
        "captures": game.captures,
        "game_over": game.game_over,
        "result": game_result(),
        "winrate_black": root.get("winrate"),
        "score_lead_black": root.get("scoreLead"),
        "winrates": [
            a.get("rootInfo", {}).get("winrate") for a in game.analysis_history
        ],
        "ownership": (
            game.analysis_history[-1].get("ownership")
            if game.analysis_history
            else None
        ),
        "last_move": game.moves[-1][1] if game.moves else None,
        # Big swings by either side, for the markers on the winrate graph.
        "key_moments": review.key_moments(game),
    }
    if extra:
        d.update(extra)
    return d


def analyze_and_store():
    a = engine.query(game, include_ownership=True)
    game.analysis_history.append(a)
    return a


def deepen(ks):
    """Re-analyse the positions at the given history indices with more visits
    and replace the stored analyses. Used to confirm a suspected big mistake
    before alarming the player, since the regular per-move search is shallow
    enough for a point or two of noise."""
    for k in sorted(ks):
        g = replay_moves(game.moves[:k])
        game.analysis_history[k] = engine.query(
            g, max_visits=MISTAKE_CONFIRM_VISITS, include_ownership=True
        )


def check_player_mistake(i):
    """If the player's move at index i looks like a big mistake, confirm it
    with a deeper search of the positions before and after it. Returns the
    confirmed swing, or None."""
    swing = review.move_swing(game, i)
    if not swing or not swing["big"]:
        return None
    deepen([i, i + 1])
    swing = review.move_swing(game, i)
    return swing if swing and swing["big"] else None


def replay_moves(moves):
    """Rebuild a Game with the current game's settings from a move prefix."""
    g = Game(
        size=game.size,
        komi=game.komi,
        player_color=game.player_color,
        rank=game.rank,
    )
    for c, m in moves:
        if m == "pass":
            g.play(is_pass=True)
        else:
            x, y = g.gtp_to_coord(m)
            g.play(x, y)
    return g


def user_move_indices():
    """Analysis indices (before, after) surrounding the player's most recent move.

    analysis_history[k] is the analysis of the position after the first k
    moves, so for the player's move at game.moves[i] the position before it is
    index i and the position after it is index i + 1. Returns (None, None)
    if the player hasn't moved yet.
    """
    user_letter = "B" if game.player_color == "black" else "W"
    if game.moves and game.moves[-1][0] == user_letter:
        i = len(game.moves) - 1
    elif len(game.moves) >= 2 and game.moves[-2][0] == user_letter:
        i = len(game.moves) - 2
    else:
        return None, None
    return i, i + 1


def player_point_loss():
    """Point loss of the player's most recent move from the player's
    perspective (negative = lost points), or None."""
    before, _ = user_move_indices()
    swing = review.move_swing(game, before) if before is not None else None
    return -swing["loss"] if swing else None


def worst_player_mistake_index():
    """History index of the position just BEFORE the player's costliest
    flagged move, so the coach can see what was available there. None if
    nothing has been flagged."""
    player = [m for m in review.key_moments(game) if m["by_player"]]
    if not player:
        return None
    return max(player, key=lambda m: m["loss"])["index"]


def snapshots_for(ks):
    ks = sorted(
        {k for k in ks if k is not None and 0 <= k < len(game.analysis_history)}
    )
    return [(k, game.analysis_history[k]) for k in ks]


def comment_payload():
    """Snapshots (before the player's move, after it, current, and before the
    player's worst mistake so far) plus point loss, for commenting on the
    player's most recent move."""
    before, after = user_move_indices()
    cur = len(game.analysis_history) - 1
    snaps = snapshots_for([before, after, cur, worst_player_mistake_index()])
    return snaps, player_point_loss()


def do_ai_move():
    mv = engine.pick_human_move(game)
    if mv is None:
        game.play(is_pass=True)
        played = "pass"
    else:
        ok, _ = game.play(mv[0], mv[1])
        played = game.moves[-1][1] if ok else "pass"
        if not ok:
            game.play(is_pass=True)
    analyze_and_store()
    return played


@app.route("/")
def index():
    return render_template(
        "index.html", coach_models=COACH_MODELS, default_coach_model=DEFAULT_COACH_MODEL
    )


@app.route("/new_game", methods=["POST"])
def new_game():
    global game
    d = request.json
    with state_lock:
        game = Game(
            size=int(d["size"]),
            komi=float(d["komi"]),
            player_color=d["player_color"],
            rank=d["rank"],
        )
        coach.chat_history = []
        analyze_and_store()
        ai_move_info = None
        if game.player_color == "white":
            ai_move_info = do_ai_move()
        return jsonify(board_state({"ai_move": ai_move_info}))


@app.route("/play", methods=["POST"])
def play():
    d = request.json
    with state_lock:
        if d.get("pass"):
            ok, err = game.play(is_pass=True)
        else:
            ok, err = game.play(d["x"], d["y"])
        if not ok:
            return jsonify({"error": err})
        analyze_and_store()
        # Confirm (and, if real, keep) a big mistake before the AI replies, so
        # the deeper numbers are what the ledger and graph show from now on.
        flagged = check_player_mistake(len(game.moves) - 1)
        user_loss = player_point_loss()

        ai_move_info = None
        if not game.game_over:
            ai_move_info = do_ai_move()

        # Auto-comment is generated AFTER the AI's reply so that what the
        # coach calls the current position matches the board the user sees.
        auto_comment = None
        if d.get("auto_comment"):
            snaps, loss = comment_payload()
            auto_comment = coach.ask("comment", game, snaps, loss, model=d.get("model"))

        # A flagged mistake gets its own comment when the player asked to be
        # told - unless auto-comment already covered the move.
        mistake_comment = None
        if flagged and d.get("flag_mistakes") and not auto_comment:
            snaps, loss = comment_payload()
            mistake_comment = coach.ask(
                "mistake", game, snaps, loss, model=d.get("model")
            )

        return jsonify(
            board_state(
                {
                    "ai_move": ai_move_info,
                    "user_point_loss": user_loss,
                    "auto_comment": auto_comment,
                    "flagged_mistake": flagged,
                    "mistake_comment": mistake_comment,
                }
            )
        )


@app.route("/coach", methods=["POST"])
def coach_route():
    d = request.json
    mode = d["mode"]
    question = d.get("question")
    model = d.get("model")
    with state_lock:
        n = len(game.analysis_history)
        if mode == "comment":
            snaps, loss = comment_payload()
        elif mode == "chat":
            # The two most recent positions, plus the position before the
            # player's worst mistake so "where did I go wrong?" can be answered.
            snaps = snapshots_for([n - 2, n - 1, worst_player_mistake_index()])
            loss = player_point_loss()
        elif mode in ("hint", "suggest"):
            snaps = snapshots_for([n - 2, n - 1])
            loss = None
        else:
            return jsonify({"error": f"Unknown coach mode: {mode}"})
        text = coach.ask(mode, game, snaps, loss, question, model=model)
        return jsonify({"text": text})


@app.route("/review", methods=["POST"])
def review_route():
    """Post-game review: confirm the biggest swings of the game with a deeper
    search, then have the coach walk through the moments that decided it."""
    d = request.json or {}
    with state_lock:
        if not game.game_over:
            return jsonify({"error": "The game isn't over yet."})
        moments = review.key_moments(game)
        deepen(review.unconfirmed_positions(game, moments))
        moments = review.key_moments(game)  # re-rank on the confirmed numbers
        # Snapshots of the positions just before each key moment (where the
        # better move was available) plus the final position.
        snaps = snapshots_for([m["index"] for m in moments] + [len(game.moves)])
        text = coach.ask(
            "review", game, snaps, None, game_result(), model=d.get("model")
        )
        # Include the board state: the deeper search may have sharpened the
        # winrates and markers the graph shows.
        return jsonify(board_state({"text": text, "moments": moments}))


@app.route("/undo", methods=["POST"])
def undo():
    """Take back the player's most recent move (and the AI's reply to it)."""
    global game
    with state_lock:
        user_letter = "B" if game.player_color == "black" else "W"
        idx = None
        for i in range(len(game.moves) - 1, -1, -1):
            if game.moves[i][0] == user_letter:
                idx = i
                break
        if idx is None:
            return jsonify({"error": "Nothing to undo yet."})
        kept = game.moves[:idx]
        analyses = game.analysis_history[: idx + 1]
        new_game = replay_moves(kept)
        new_game.analysis_history = analyses
        game = new_game
        return jsonify(board_state())


@app.route("/resign", methods=["POST"])
def resign():
    with state_lock:
        if not game.game_over:
            game.game_over = True
            game.result = "W+R" if game.player_color == "black" else "B+R"
        return jsonify(board_state())


@app.route("/position")
def position():
    """Read-only view of the position after the first k moves (for review)."""
    with state_lock:
        k = max(0, min(int(request.args.get("k", 0)), len(game.moves)))
        g = replay_moves(game.moves[:k])
        a = (game.analysis_history[k] if k < len(game.analysis_history) else None) or {}
        return jsonify(
            {
                "k": k,
                "board": g.board,
                "last_move": g.moves[-1][1] if g.moves else None,
                "winrate_black": a.get("rootInfo", {}).get("winrate"),
                "score_lead_black": a.get("rootInfo", {}).get("scoreLead"),
                "ownership": a.get("ownership"),
            }
        )


@app.route("/sgf")
def sgf():
    """Download the current game as an SGF file."""
    with state_lock:
        rank_label = game.rank.replace("rank_", "")
        player, ai = "Player", f"KataGo ({rank_label})"
        pb, pw = (player, ai) if game.player_color == "black" else (ai, player)
        header = (
            f"(;FF[4]GM[1]CA[UTF-8]AP[GoTeacher]SZ[{game.size}]"
            f"KM[{game.komi}]RU[Japanese]PB[{pb}]PW[{pw}]"
        )
        result = game_result()
        if result:
            header += f"RE[{result.replace(' (estimate)', '')}]"
        body = ""
        for c, m in game.moves:
            if m == "pass":
                coord = ""
            else:
                x, y = game.gtp_to_coord(m)
                coord = chr(97 + x) + chr(97 + y)
            body += f";{c}[{coord}]"
        return Response(
            header + body + ")",
            mimetype="application/x-go-sgf",
            headers={"Content-Disposition": "attachment; filename=go-teacher.sgf"},
        )


def main():
    global engine, coach, game
    for path, name in [(KATAGO_EXE, "KataGo executable"), (MAIN_MODEL, "main model")]:
        if not os.path.exists(path):
            print(f"ERROR: {name} not found at: {path}")
            print("Edit the CONFIG section in goteacher/config.py.")
            sys.exit(1)
    engine = KataGo()
    coach = Coach()
    game = Game()
    print(f"\nReady. Open http://localhost:{PORT} in your browser.\n")
    app.run(port=PORT, debug=False)
