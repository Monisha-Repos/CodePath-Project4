"""
Command line runner for TuneMatch.

    python -m src.main                       # original demo: 8 fixed profiles (no LLM)
    python -m src.main --ask "chill lofi"    # RAG: one plain-English request
    python -m src.main --chat                # RAG: interactive, type 'quit' to exit
    python -m src.main --ask "..." --no-llm  # RAG pipeline with the rule-based fallbacks only

    Add --agent to --ask/--chat to let the agent check and revise its search
    before answering, and --save-trace to write its reasoning to traces/.
"""

import argparse
import logging
import os

try:
    from src.recommender import load_songs, recommend_songs  # python -m src.main
    from src.llm_client import GeminiClient, LLMError
    from src.rag import answer_request, InputError, RAGResult
    from src.agent import AgentResult, describe_profile, run_agent, save_trace
except ImportError:
    from recommender import load_songs, recommend_songs  # python src/main.py
    from llm_client import GeminiClient, LLMError
    from rag import answer_request, InputError, RAGResult
    from agent import AgentResult, describe_profile, run_agent, save_trace

SONGS_PATH = "data/songs.csv"
LOG_PATH = "logs/app.log"


# genre_prefs / mood_prefs are shares of the user's listening history;
# each is scored relative to the user's top choice.
PROFILES = {
    # Starter example profile (shown in the README sample output)
    "Default Pop/Happy": {
        "genre": "pop", "mood": "happy", "energy": 0.8,
        "genre_prefs": {"pop": 0.5, "lofi": 0.3, "rock": 0.2},
        "mood_prefs": {"happy": 0.6, "chill": 0.4},
    },

    # --- Typical listeners ---
    "High-Energy Pop": {
        "genre": "pop", "mood": "happy", "energy": 0.9, "likes_acoustic": False,
    },
    "Chill Lofi": {
        "genre": "lofi", "mood": "chill", "energy": 0.35, "likes_acoustic": True,
        "genre_prefs": {"lofi": 0.60, "jazz": 0.25, "ambient": 0.15},
        "mood_prefs": {"chill": 0.70, "focused": 0.30},
    },
    "Deep Intense Rock": {
        "genre": "rock", "mood": "intense", "energy": 0.95, "likes_acoustic": False,
        "genre_prefs": {"rock": 0.60, "metal": 0.40},
        "mood_prefs": {"intense": 0.60, "angry": 0.40},
    },

    # --- Edge cases: trying to trick the scoring ---
    # Conflicting: wants high energy but a sad mood (sad songs here are calm).
    "Sad but Hyped": {
        "genre": "blues", "mood": "sad", "energy": 0.9, "likes_acoustic": False,
    },
    # Favorite genre isn't in the catalog at all.
    "Ghost Genre (k-pop)": {
        "genre": "k-pop", "mood": "happy", "energy": 0.7, "likes_acoustic": False,
    },
    # Loves metal, but also wants acoustic sound (no song is both).
    "Acoustic Headbanger": {
        "genre": "metal", "mood": "angry", "energy": 0.95, "likes_acoustic": True,
    },
    # Listens to everything equally, middle energy, no acoustic preference.
    "Fence Sitter": {
        "genre": "pop", "mood": "happy", "energy": 0.5,
        "genre_prefs": {"pop": 0.25, "rock": 0.25, "jazz": 0.25, "country": 0.25},
        "mood_prefs": {"happy": 0.5, "sad": 0.5},
    },
}


def run_demo(songs: list) -> None:
    """Prints the top 5 songs for every fixed profile (the original Project 3 demo)."""
    print(f"Loaded songs: {len(songs)}")
    for name, user_prefs in PROFILES.items():
        recommendations = recommend_songs(user_prefs, songs, k=5)
        print_recommendations(name, user_prefs, recommendations)


def setup_logging() -> None:
    """Writes a detailed log of every run to logs/app.log."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def make_llm(use_llm: bool):
    """Returns a GeminiClient, or None (rules-only mode) if disabled or unavailable."""
    if not use_llm:
        return None
    try:
        return GeminiClient()
    except LLMError as e:
        logging.getLogger(__name__).warning("LLM unavailable: %s", e)
        print(f"[!] {e}\n[!] Running in rules-only mode.\n")
        return None


def ask(request: str, songs: list, llm, use_agent: bool = False, trace_file: bool = False) -> None:
    """Runs one request through the RAG pipeline (or the agent) and prints the answer."""
    try:
        result = run_agent(request, songs, llm) if use_agent else answer_request(request, songs, llm)
    except InputError as e:
        print(f"[!] {e}")
        return
    print_rag_result(result)
    if use_agent and trace_file:
        print(f"  Trace saved to {save_trace(result)}\n")


def print_agent_steps(result: AgentResult) -> None:
    """Prints the agent's plan / act / check / revise steps."""
    print("  Agent steps:")
    for i, step in enumerate(result.trace, start=1):
        print(f"   {i}. {step.step:<6} {step.detail}")
    for change in result.agent_changes:
        print(f"  [agent] {change}")


def print_rag_result(result: RAGResult) -> None:
    """Prints how the request was understood, the picks, and reliability info."""
    print("\n" + "=" * 60)
    print(f'  Request: "{result.request}"')
    print("=" * 60)
    for error in result.llm_errors:
        print(f"  [!] {error} Using the rule-based fallback.")

    if result.off_topic:
        print(f"  {result.note}\n")
        return

    if isinstance(result, AgentResult):
        print_agent_steps(result)
        print(f"  Final profile -> {describe_profile(result.profile)}")
    else:
        print(f"  Understood as -> {describe_profile(result.profile)}")
    for warning in result.warnings:
        print(f"  [!] {warning}")
    print("-" * 60)

    if result.intro:
        print(f"\n  {result.intro}")
    for rank, pick in enumerate(result.picks, start=1):
        s = pick.song
        print(f"\n  {rank}. {s['title']} by {s['artist']}  ({s['genre']} / {s['mood']}, match {pick.score:.2f})")
        print(f"     {pick.why}")
    if result.note:
        print(f"\n  Note: {result.note}")

    print("\n" + "-" * 60)
    print(f"  Confidence: {result.confidence:.2f} | retrieved {len(result.retrieved)} candidates"
          f" | parsed by: {result.parsed_by} | written by: {result.written_by}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="TuneMatch music recommender")
    parser.add_argument("--ask", metavar="REQUEST", help="get recommendations for one plain-English request")
    parser.add_argument("--chat", action="store_true", help="interactive mode")
    parser.add_argument("--no-llm", action="store_true", help="skip Gemini and use the rule-based fallbacks")
    parser.add_argument("--agent", action="store_true", help="let the agent check and revise its search before answering")
    parser.add_argument("--save-trace", action="store_true", help="with --agent: save the reasoning trace to traces/")
    args = parser.parse_args()

    setup_logging()
    songs = load_songs(SONGS_PATH)

    if args.ask is None and not args.chat:
        run_demo(songs)
        return

    llm = make_llm(not args.no_llm)
    if args.ask is not None:
        ask(args.ask, songs, llm, args.agent, args.save_trace)
    if args.chat:
        print("TuneMatch: describe what you want to hear (type 'quit' to exit).")
        while True:
            try:
                request = input("\n> ")
            except (EOFError, KeyboardInterrupt):
                break
            if request.strip().lower() in {"quit", "exit", "q"}:
                break
            ask(request, songs, llm, args.agent, args.save_trace)


def print_recommendations(name: str, user_prefs: dict, recommendations: list) -> None:
    """Prints each recommendation with its score and the reasons behind it."""
    genres = ", ".join(f"{g} {share:.0%}" for g, share in user_prefs.get("genre_prefs", {}).items())
    moods = ", ".join(f"{m} {share:.0%}" for m, share in user_prefs.get("mood_prefs", {}).items())
    acoustic = user_prefs.get("likes_acoustic")
    print("\n" + "=" * 60)
    print(f"  Top Recommendations: {name}")
    print("=" * 60)
    print(f"  Genres: {genres or user_prefs.get('genre')}")
    print(f"  Moods:  {moods or user_prefs.get('mood')}")
    print(f"  Target energy: {user_prefs.get('energy')}")
    if acoustic is not None:
        print(f"  Likes acoustic: {'yes' if acoustic else 'no'}")
    print("-" * 60)

    for rank, (song, score, explanation) in enumerate(recommendations, start=1):
        print(f"\n{rank}. {song['title']} by {song['artist']}")
        print(f"   {song['genre']} / {song['mood']}   Score: {score:.2f}")
        for reason in explanation.split(", "):
            print(f"     - {reason}")
    print()


if __name__ == "__main__":
    main()
