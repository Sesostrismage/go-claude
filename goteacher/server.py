"""Flask server: routes that tie the Game, KataGo engine, and Coach together."""

import os
import sys
import threading

try:
    from flask import Flask, jsonify, render_template, request
except ImportError:
    print("Missing dependency: pip install flask")
    sys.exit(1)

from .coach import Coach
from .config import COACH_MODELS, DEFAULT_COACH_MODEL, KATAGO_EXE, MAIN_MODEL, PORT
from .engine import KataGo
from .rules import Game

app = Flask(__name__)
engine = None
coach = None
game = None
state_lock = threading.Lock()


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
        "winrate_black": root.get("winrate"),
        "score_lead_black": root.get("scoreLead"),
        "last_move": game.moves[-1][1] if game.moves else None,
    }
    if extra:
        d.update(extra)
    return d


def analyze_and_store():
    a = engine.query(game)
    game.analysis_history.append(a)
    return a


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


def point_loss_between(before, after):
    """Point loss of the player's move between two analysis indices, from the player's
    perspective."""
    if before is None:
        return None
    prev, cur = game.analysis_history[before], game.analysis_history[after]
    if not prev.get("moveInfos"):
        return None
    best = prev["moveInfos"][0]["scoreLead"]
    actual = cur["rootInfo"]["scoreLead"]
    user_is_black = game.player_color == "black"
    return (actual - best) if user_is_black else (best - actual)


def comment_payload():
    """Snapshots (before the player's move, after it, current) plus point loss,
    for commenting on the player's most recent move."""
    before, after = user_move_indices()
    cur = len(game.analysis_history) - 1
    ks = sorted({k for k in (before, after, cur) if k is not None})
    return [(k, game.analysis_history[k]) for k in ks], point_loss_between(
        before, after
    )


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
        user_loss = point_loss_between(*user_move_indices())

        ai_move_info = None
        if not game.game_over:
            ai_move_info = do_ai_move()

        # Auto-comment is generated AFTER the AI's reply so that what the
        # coach calls the current position matches the board the user sees.
        auto_comment = None
        if d.get("auto_comment"):
            snaps, loss = comment_payload()
            auto_comment = coach.ask("comment", game, snaps, loss, model=d.get("model"))

        return jsonify(
            board_state(
                {
                    "ai_move": ai_move_info,
                    "user_point_loss": user_loss,
                    "auto_comment": auto_comment,
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
        if mode == "comment":
            snaps, loss = comment_payload()
        else:  # hint / suggest / chat: the two most recent positions
            n = len(game.analysis_history)
            snaps = [(k, game.analysis_history[k]) for k in (n - 2, n - 1) if k >= 0]
            loss = None
        text = coach.ask(mode, game, snaps, loss, question, model=model)
        return jsonify({"text": text})


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
