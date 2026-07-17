"""KataGo engine wrapper: launches katago in analysis mode and queries it."""

import json
import os
import random
import subprocess
import sys
import threading

from .config import ANALYSIS_VISITS, HUMAN_MODEL, KATAGO_EXE, MAIN_MODEL, PROJECT_ROOT
from .rules import Game


class KataGo:
    def __init__(self):
        cfg_path = os.path.join(PROJECT_ROOT, "analysis.cfg")
        with open(cfg_path, "w") as f:
            f.write(
                "numAnalysisThreads = 1\n"
                "numSearchThreads = 8\n"
                "nnMaxBatchSize = 32\n"
                "reportAnalysisWinratesAs = BLACK\n"
            )
        cmd = [KATAGO_EXE, "analysis", "-config", cfg_path, "-model", MAIN_MODEL]
        if HUMAN_MODEL and os.path.exists(HUMAN_MODEL):
            cmd += ["-human-model", HUMAN_MODEL]
            self.has_human_model = True
        else:
            self.has_human_model = False
            print("WARNING: human model not found - AI opponent will use the")
            print("         main network with reduced visits instead.")
        print("Starting KataGo (first OpenCL run may take a few minutes to tune)...")
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.lock = threading.Lock()
        self.query_id = 0
        self.ready = threading.Event()

        def _pump_stderr():
            for line in self.proc.stderr:
                print(f"[katago] {line.rstrip()}")
                if "ready to begin handling requests" in line.lower():
                    self.ready.set()
            # stderr closed = process exited
            self.ready.set()

        threading.Thread(target=_pump_stderr, daemon=True).start()
        self.ready.wait()
        try:
            self.proc.wait(timeout=1)  # give a crashed process time to fully exit
        except subprocess.TimeoutExpired:
            pass
        if self.proc.poll() is not None:
            print("\nERROR: KataGo exited during startup. See [katago] lines above")
            print("for the reason (usually a wrong model path or config issue).")
            sys.exit(1)
        print("KataGo is ready.")

    def query(
        self,
        game: Game,
        max_visits=ANALYSIS_VISITS,
        include_policy=False,
        human_profile=None,
    ):
        with self.lock:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    "KataGo process has exited. Restart the server and check the [katago] log lines for errors."
                )
            self.query_id += 1
            qid = f"q{self.query_id}"
            q = {
                "id": qid,
                "moves": [[c, m] for c, m in game.moves],
                "rules": "japanese",
                "komi": game.komi,
                "boardXSize": game.size,
                "boardYSize": game.size,
                "maxVisits": max_visits,
            }
            if include_policy:
                q["includePolicy"] = True
            if human_profile and self.has_human_model:
                q["overrideSettings"] = {"humanSLProfile": human_profile}
            self.proc.stdin.write(json.dumps(q) + "\n")
            self.proc.stdin.flush()
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError("KataGo terminated unexpectedly.")
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if resp.get("id") == qid:
                    if "error" in resp:
                        raise RuntimeError(f"KataGo error: {resp['error']}")
                    if "warning" in resp and "rootInfo" not in resp:
                        continue  # warning line, not the actual result
                    return resp

    def pick_human_move(self, game: Game):
        """Sample the AI opponent's move from the human-style policy."""
        resp = self.query(
            game, max_visits=40, include_policy=True, human_profile=game.rank
        )
        policy = resp.get("humanPolicy") or resp.get("policy")
        legal = game.legal_moves_mask()
        candidates = []
        n = game.size
        for i, p in enumerate(policy):
            if p is None or p < 0:
                continue
            if i == n * n:  # pass
                candidates.append((p, None))
            else:
                x, y = i % n, i // n
                if (x, y) in legal:
                    candidates.append((p, (x, y)))
        if not candidates:
            return None  # pass
        candidates.sort(reverse=True, key=lambda c: c[0])
        top = candidates[:12]
        total = sum(p for p, _ in top)
        r = random.random() * total
        acc = 0
        for p, mv in top:
            acc += p
            if r <= acc:
                return mv
        return top[0][1]
