import os
import json
import requests
import chess
import chess.engine
import chess.pgn
from io import StringIO

# === CONFIG ===
CONVEX_URL = "https://famous-buzzard-906.convex.cloud"
LICHESS_API = "https://lichess.org/api/games/user/"
STOCKFISH_PATH = "/usr/games/stockfish"

MAX_GAMES = 30
BATCH_SIZE = 5
TARGET_PUZZLES = 8
MIN_EVAL_SWING = 1.5

# === HELPERS ===

def fetch_games(username, max_games=30):
    """Fetch PGN text for last max_games games"""
    url = f"{LICHESS_API}{username}?max={max_games}&analysed=true"
    print(f"📥 Fetching games from {url}")
    resp = requests.get(url)
    if resp.status_code != 200:
        raise Exception(f"Lichess fetch error: {resp.text}")
    return resp.text

def parse_pgns(pgn_text):
    """Parse PGN text into list of game objects"""
    games = []
    pgn_io = StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            break
        games.append(game)
    return games

def analyze_game(engine, game):
    """Analyze one game for tactical eval swings"""
    board = game.board()
    puzzles = []
    prev_eval = None

    for move in game.mainline_moves():
        board.push(move)
        info = engine.analyse(board, chess.engine.Limit(depth=18))
        score = info["score"].pov(board.turn).score(mate_score=10000) / 100.0

        if prev_eval is not None:
            swing = abs(score - prev_eval)
            if swing >= MIN_EVAL_SWING:
                puzzles.append({
                    "fen": board.fen(),
                    "swing": round(swing, 2),
                    "last_move": move.uci(),
                    "eval": round(score, 2)
                })
        prev_eval = score
    return puzzles

def store_cache(username, data):
    """Store PGNs locally"""
    with open(f"/tmp/rooket_{username}.json", "w") as f:
        json.dump(data, f)

def load_cache(username):
    """Load cached games if exist"""
    try:
        with open(f"/tmp/rooket_{username}.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def upload_to_convex(username, puzzles):
    """Upload analyzed puzzles to Convex backend"""
    endpoint = f"{CONVEX_URL}/api/rooket_upload"
    payload = {
        "username": username,
        "puzzles": puzzles
    }
    print(f"☁️ Uploading {len(puzzles)} puzzles to Convex...")
    try:
        resp = requests.post(endpoint, json=payload)
        print(f"Convex response: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"⚠️ Failed to upload to Convex: {e}")

# === MAIN LOGIC ===

def generate_puzzles(username):
    print(f"🔍 Starting analysis for {username}...")
    cached = load_cache(username)
    if cached:
        print("♻️ Using cached PGNs.")
        games = [chess.pgn.read_game(StringIO(pgn)) for pgn in cached]
    else:
        pgn_text = fetch_games(username, MAX_GAMES)
        games = parse_pgns(pgn_text)
        store_cache(username, [str(g) for g in games])

    puzzles = []
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

    for i in range(0, len(games), BATCH_SIZE):
        batch = games[i:i + BATCH_SIZE]
        print(f"⚡ Analyzing batch {i//BATCH_SIZE + 1} ({len(batch)} games)")
        for game in batch:
            found = analyze_game(engine, game)
            puzzles.extend(found)
            if len(puzzles) >= TARGET_PUZZLES:
                break
        if len(puzzles) >= TARGET_PUZZLES:
            break

    engine.quit()
    puzzles = sorted(puzzles, key=lambda x: x["swing"], reverse=True)[:TARGET_PUZZLES]

    print(f"✅ {len(puzzles)} tactical puzzles ready for upload.")
    upload_to_convex(username, puzzles)
    return puzzles

# === ENTRY POINT ===
if __name__ == "__main__":
    username = os.getenv("LICHESS_USER", "MagnusCarlsen")  # fallback test
    generate_puzzles(username)
