"""Flask server: routes that tie the Game, KataGo engine, and Coach together."""

import os
import sys
import threading

try:
    from flask import Flask, Response, jsonify, render_template, request
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
    }
    if extra:
        d.update(extra)
    return d


def analyze_and_store():
    a = engine.query(game, include_ownership=True)
    game.analysis_history.append(a)
    return a


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
        a = (
            game.analysis_history[k]
            if k < len(game.analysis_history)
            else None
        ) or {}
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
