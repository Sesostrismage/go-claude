"""Go rules and board state: the Game class."""

import hashlib

GTP_COLS = "ABCDEFGHJKLMNOPQRST"  # no I


class Game:
    def __init__(self, size=19, komi=6.5, player_color="black", rank="rank_5k"):
        self.size = size
        self.komi = komi
        self.player_color = player_color  # "black" or "white"
        self.rank = rank
        self.board = [[0] * size for _ in range(size)]  # 0 empty, 1 black, 2 white
        self.to_move = 1  # black starts
        self.moves = []  # list of ("B"/"W", "D4"/"pass")
        self.captures = {1: 0, 2: 0}
        self.position_hashes = {self._hash()}
        self.consecutive_passes = 0
        self.game_over = False
        self.analysis_history = []  # analysis dict after each move

    def _hash(self):
        return hashlib.md5(
            (
                str(self.to_move) + "".join("".join(map(str, r)) for r in self.board)
            ).encode()
        ).hexdigest()

    def _neighbors(self, x, y):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.size and 0 <= ny < self.size:
                yield nx, ny

    def _group_and_liberties(self, x, y, board):
        color = board[y][x]
        group, libs, stack, seen = [], set(), [(x, y)], {(x, y)}
        while stack:
            cx, cy = stack.pop()
            group.append((cx, cy))
            for nx, ny in self._neighbors(cx, cy):
                if board[ny][nx] == 0:
                    libs.add((nx, ny))
                elif board[ny][nx] == color and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        return group, libs

    def legal_moves_mask(self):
        """Return set of legal (x, y) for the player to move."""
        legal = set()
        for y in range(self.size):
            for x in range(self.size):
                if self.board[y][x] == 0 and self._try_move(x, y, dry=True):
                    legal.add((x, y))
        return legal

    def _try_move(self, x, y, dry=False):
        """Attempt move for self.to_move. Returns False if illegal.
        If dry, board is restored."""
        if self.board[y][x] != 0:
            return False
        color, enemy = self.to_move, 3 - self.to_move
        board = [row[:] for row in self.board]
        board[y][x] = color
        captured = []
        for nx, ny in self._neighbors(x, y):
            if board[ny][nx] == enemy:
                grp, libs = self._group_and_liberties(nx, ny, board)
                if not libs:
                    captured.extend(grp)
        for cx, cy in captured:
            board[cy][cx] = 0
        _, own_libs = self._group_and_liberties(x, y, board)
        if not own_libs:
            return False  # suicide
        # superko check
        h = hashlib.md5(
            (str(enemy) + "".join("".join(map(str, r)) for r in board)).encode()
        ).hexdigest()
        if h in self.position_hashes:
            return False
        if dry:
            return True
        self.board = board
        self.captures[color] += len(captured)
        self.position_hashes.add(h)
        return True

    def play(self, x=None, y=None, is_pass=False):
        if self.game_over:
            return False, "Game is over."
        color_letter = "B" if self.to_move == 1 else "W"
        if is_pass:
            self.moves.append((color_letter, "pass"))
            self.consecutive_passes += 1
            self.to_move = 3 - self.to_move
            if self.consecutive_passes >= 2:
                self.game_over = True
            return True, None
        if not self._try_move(x, y):
            return False, "Illegal move."
        self.consecutive_passes = 0
        self.moves.append((color_letter, self.coord_to_gtp(x, y)))
        self.to_move = 3 - self.to_move
        return True, None

    def coord_to_gtp(self, x, y):
        return f"{GTP_COLS[x]}{self.size - y}"

    def gtp_to_coord(self, gtp):
        if gtp.lower() == "pass":
            return None
        x = GTP_COLS.index(gtp[0].upper())
        y = self.size - int(gtp[1:])
        return x, y

    def ascii_board(self):
        header = "   " + " ".join(GTP_COLS[: self.size])
        rows = []
        for y in range(self.size):
            row_num = str(self.size - y).rjust(2)
            cells = " ".join(".XO"[self.board[y][x]] for x in range(self.size))
            rows.append(f"{row_num} {cells}")
        return header + "\n" + "\n".join(rows) + "\n(X = Black, O = White)"
