"""
Tests for the agent loop (plan -> act -> check -> revise -> answer).
Uses scripted fake LLM responses, so they run offline and are repeatable.
"""

from src.agent import (
    MAX_REVISIONS, check_results, format_trace, rule_based_revision, run_agent, search_catalog,
)
from src.llm_client import LLMError
from src.rag import catalog_vocab, validate_profile
from src.recommender import load_songs
from tests.test_rag import FakeLLM

SONGS = load_songs("data/songs.csv")
GENRES, MOODS = catalog_vocab(SONGS)


def profile(**raw):
    return validate_profile(raw, GENRES, MOODS)[0]


def issue_kinds(p):
    return [i.kind for i in check_results(p, search_catalog(p, SONGS), SONGS)]


def steps(result):
    return [s.step for s in result.trace]


# --- CHECK -----------------------------------------------------------------

def test_check_passes_for_a_well_supported_request():
    p = profile(genre_prefs={"lofi": 1}, mood_prefs={"chill": 1}, energy=0.35)
    assert issue_kinds(p) == []


def test_check_flags_energy_conflict():
    # "Sad but Hyped" from Project 3: the only sad blues song is calm.
    p = profile(genre_prefs={"blues": 1}, mood_prefs={"sad": 1}, energy=0.9)
    assert "energy_conflict" in issue_kinds(p)


def test_check_flags_acoustic_conflict():
    # "Acoustic Headbanger" from Project 3: no metal song is acoustic.
    p = profile(genre_prefs={"metal": 1}, mood_prefs={"angry": 1}, energy=0.95, likes_acoustic=True)
    assert "acoustic_conflict" in issue_kinds(p)


def test_check_skips_vague_requests():
    assert issue_kinds(profile()) == []


# --- REVISE (rule fallback) -------------------------------------------------

def test_rule_revision_drops_the_conflicting_constraint():
    p = profile(genre_prefs={"metal": 1}, likes_acoustic=True, energy=0.95)
    issues = check_results(p, search_catalog(p, SONGS), SONGS)
    revised, change = rule_based_revision(p, issues)
    assert revised["likes_acoustic"] is None
    assert revised["genre_prefs"] == {"metal": 1.0}   # keeps what the user asked for most
    assert "acoustic" in change


# --- full loop --------------------------------------------------------------

def test_agent_answers_directly_when_first_search_is_good():
    result = run_agent("chill lofi to study to", SONGS, llm=None)
    assert steps(result) == ["PLAN", "ACT", "CHECK", "ANSWER"]
    assert len(result.attempts) == 1


def test_agent_revises_conflicting_request_without_llm():
    result = run_agent("sad blues for the gym", SONGS, llm=None)

    assert "REVISE" in steps(result)
    assert result.attempts[0].issues[0].kind == "energy_conflict"
    assert result.chosen > 0                          # a revised attempt was used
    assert result.profile["energy"] is None
    assert result.picks[0].song["genre"] == "blues"
    assert result.agent_changes                       # the user is told what changed


def test_agent_uses_llm_revision_and_explains_it():
    parse = {"genre_prefs": {"metal": 1}, "mood_prefs": {"angry": 1}, "energy": 0.95,
             "likes_acoustic": True, "unavailable": [], "off_topic": False}
    # Revision 1 fixes the conflict; there's still only one metal song, so
    # revision 2 broadens to related rock / intense songs.
    revise1 = {"genre_prefs": {"metal": 1}, "mood_prefs": {"angry": 1}, "energy": 0.95,
               "likes_acoustic": None, "change": "No metal song is acoustic, so I dropped that filter."}
    revise2 = {"genre_prefs": {"metal": 0.6, "rock": 0.4}, "mood_prefs": {"angry": 0.6, "intense": 0.4},
               "energy": 0.95, "likes_acoustic": None, "change": "I added rock to find more heavy songs."}
    metal_id = next(s["id"] for s in SONGS if s["genre"] == "metal")
    answer = {"intro": "Heavy picks.", "picks": [{"id": metal_id, "why": "Pure metal."}], "note": ""}
    llm = FakeLLM(parse, revise1, revise2, answer)

    result = run_agent("acoustic metal", SONGS, llm)

    assert steps(result).count("REVISE") == 2
    assert all("(llm)" in s.detail for s in result.trace if s.step == "REVISE")
    assert result.chosen == 2                       # broadened attempt has more strong matches
    assert result.attempts[2].strong > result.attempts[1].strong
    assert result.agent_changes == ["No metal song is acoustic, so I dropped that filter.",
                                    "I added rock to find more heavy songs."]
    assert result.picks[0].song["id"] == metal_id
    assert "No metal song is acoustic" in llm.prompts[-1]   # the writer was told about the changes
    assert result.written_by == "llm"


def test_agent_stops_when_reviser_repeats_itself():
    parse = {"genre_prefs": {"blues": 1}, "mood_prefs": {"sad": 1}, "energy": 0.9}
    same = dict(parse, change="no real change")
    llm = FakeLLM(parse, same, {"picks": []})
    result = run_agent("sad blues, hype", SONGS, llm)

    assert steps(result).count("ACT") == 1
    assert "already tried" in next(s.detail for s in result.trace if s.step == "STOP")


def test_agent_respects_step_limit():
    # The reviser keeps proposing new but still-conflicting profiles.
    parse = {"genre_prefs": {"blues": 1}, "mood_prefs": {"sad": 1}, "energy": 0.9}
    revisions = [dict(parse, energy=0.9 - 0.01 * (i + 1), change=f"try {i}") for i in range(5)]
    llm = FakeLLM(parse, *revisions, {"picks": []})
    result = run_agent("sad blues, hype", SONGS, llm)

    assert steps(result).count("ACT") == MAX_REVISIONS + 1
    assert steps(result)[-2] == "STOP"


def test_agent_falls_back_to_rule_revision_when_llm_fails():
    parse = {"genre_prefs": {"blues": 1}, "mood_prefs": {"sad": 1}, "energy": 0.9}
    llm = FakeLLM(parse, LLMError("rate limited"), LLMError("rate limited"),
                  LLMError("rate limited"), LLMError("rate limited"))
    result = run_agent("sad blues, hype", SONGS, llm)

    assert "(rules)" in next(s.detail for s in result.trace if s.step == "REVISE")
    assert "rate limited" in result.llm_errors
    assert result.picks


def test_agent_declines_off_topic_requests():
    result = run_agent("write me a poem", SONGS, FakeLLM({"off_topic": True}))
    assert result.off_topic and result.picks == []
    assert steps(result) == ["PLAN"]


def test_trace_is_markdown_with_every_step():
    result = run_agent("sad blues for the gym", SONGS, llm=None)
    md = format_trace(result)
    assert md.startswith('### Agent trace: "sad blues for the gym"')
    for step in ("PLAN", "ACT", "CHECK", "REVISE", "ANSWER"):
        assert f"**{step}**" in md
