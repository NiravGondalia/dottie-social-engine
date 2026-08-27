"""Dottie Opportunity Discovery — LLM filter for meetup-worthy Reddit posts.

Keyword scan casts a wide net. This module asks: would this thread naturally
become a real-world Dottie meetup in the next ~3 weeks?
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Keep discovery completions small: JSON keepers only, no chain-of-thought.
_DISCOVERY_MAX_TOKENS = 1200
_THINKING_MIN_TOKENS = 2500
_BODY_CHARS = 250


@dataclass
class DiscoveryResult:
    """Outcome of one Dottie LLM filter pass."""

    keepers: List[Dict] = field(default_factory=list)
    evaluated_ids: List[str] = field(default_factory=list)
    skip_rejects: bool = False


SYSTEM_PROMPT = """You are an Opportunity Discovery Engine for Dottie.

Dottie is a Social OS that helps people build real friendships by matching them into small, intentional, in-person groups.

Your job is NOT to find popular Reddit posts.
Your job is to find discussions that could become real-world activities inside Dottie.

GOAL
Keep posts that could become an in-person Dottie group in the next 3 weeks
(this week + the next two weekends). Dated public events, monthly meetups,
cinema/socials, rec-league, hikes, and open invites MUST be kept even if the
date is 8–21 days out. Do NOT drop a real meetup because it is not today.
"Looking for people to play pickleball / hike / coffee / language exchange"
is a meetup seed — keep it. Pure product/info questions ("best internet",
"used car", "where to buy") are not.
Omit events whose date is already in the past.

Think: "People could meet because of this." Prefer several keepers over a
single "best" post. Return every qualifier, up to MAX_RESULTS.

HIGH VALUE: sports/running/hiking/cycling/walking/pickleball/volleyball/tennis/badminton/soccer/basketball; coffee/brunch/restaurants/food festivals/farmers markets; concerts/live music/comedy/theatre/festivals/galleries/museums; language exchange/book clubs/board games/trivia/chess/coding/AI/startup networking/hackathons; volunteering/beach or park cleanups/community events; photography walks/sunset spots/picnics/dog walks; weekend plans; "I'm new in Toronto"; "looking for friends"; "anyone interested"; "who wants to join".

EXCLUDE forever: medical, healthcare, mental health, legal, government, taxes, immigration, housing, landlords, utilities, mechanics, repairs, cleaning, shopping, financial advice, insurance, tattoos, beauty, hair salons, pet services/cremation/vet, home services, customer support, complaints, rants, politics, crime, news, traffic, emergency reporting, product recommendations, dating/hookups, 1:1 only, private house parties with no public angle, sold-out or invite-only events with no public walk-up. Open public meetups, hikes, coffee hangs, and rec-league style invites SHOULD be kept.

DOTTIE SCORE (sum, max 12)
+3 People could meet because of it
+2 Public place
+2 Easy to organize
+2 Repeatable every week
+1 Works with strangers
+1 Group size 3–8
+1 Appeals to ages 20–40
Only keep posts with dottie_score >= MIN_DOTTIE_SCORE.

Also score:
social_potential 0–5 (memorable moments / photos / videos)
recurring_potential 0–5 (weekly/monthly event potential)
community_growth 0–5 (invite friends / return)

Final score (0–10 scale) =
  0.4 * (dottie_score/12*10) + 0.3 * (social_potential/5*10) + 0.3 * (community_growth/5*10)

QUALITY BAR: "If Dottie existed, would this Reddit thread naturally become a meetup in the next 3 weeks?" If NO, omit it.

OUTPUT: Return ONLY a JSON object (no markdown, no think tags, no prose).
Shape: {"keepers":[ ... ]}
Each kept item MUST use only these keys (do not copy title, url, or body):
{
  "target_id": "...",
  "dottie_score": 10,
  "social_potential": 4,
  "recurring_potential": 3,
  "community_growth": 4,
  "final_score": 7.5,
  "activity_type": "hike",
  "why": "public hike, open invite",
  "meetup_title": "short title",
  "urgency": "Today | This Week | This Month"
}
why <= 20 words. Omit rejects. If none qualify: {"keepers":[]}.
Return ALL qualifying items up to MAX_RESULTS, ranked by final_score desc. Do not return only one if several qualify.
"""


_JSON_OBJECT = {"type": "json_object"}
_RETRY_PROMPT = (
    "Your previous reply was not valid JSON. "
    "Reply with only a JSON object: {\"keepers\":[...]} . "
    "No markdown, no think tags, no prose."
)


def _keepers_from_data(data: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(data, dict):
        items = data.get("keepers")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
        return None
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return None


def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    """Parse keepers from LLM JSON object or array.

    Prefers {"keepers":[...]} (JSON mode). Falls back to the last JSON array
    so thinking text with stray brackets does not win. Returns None when
    unparseable so callers can retry instead of treating it as "none qualify."
    """
    if not text or not str(text).strip():
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.S | re.I)
    cleaned = cleaned.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = _keepers_from_data(json.loads(cleaned))
        if parsed is not None:
            return parsed
    except json.JSONDecodeError:
        pass

    obj_start = cleaned.find("{")
    obj_end = cleaned.rfind("}")
    if obj_start >= 0 and obj_end > obj_start:
        try:
            parsed = _keepers_from_data(json.loads(cleaned[obj_start : obj_end + 1]))
            if parsed is not None:
                return parsed
        except json.JSONDecodeError:
            pass

    idx = len(cleaned)
    while True:
        start = cleaned.rfind("[", 0, idx)
        if start < 0:
            break
        end = cleaned.rfind("]")
        if end <= start:
            idx = start
            continue
        try:
            parsed = _keepers_from_data(json.loads(cleaned[start : end + 1]))
            if parsed is not None:
                return parsed
        except json.JSONDecodeError:
            pass
        idx = start

    logger.warning(
        "Dottie discovery: failed to parse LLM JSON preview=%r",
        cleaned[:400],
    )
    return None


def _final_score(dottie: float, social: float, community: float) -> float:
    return round(
        0.4 * (dottie / 12.0 * 10.0)
        + 0.3 * (social / 5.0 * 10.0)
        + 0.3 * (community / 5.0 * 10.0),
        2,
    )


def discovery_enabled(project: Dict) -> bool:
    cfg = project.get("opportunity_discovery") or {}
    if cfg.get("enabled"):
        return True
    name = (project.get("project") or {}).get("name", "")
    return name.lower() == "dottie"


def filter_opportunities(
    llm,
    opportunities: List[Dict],
    project: Dict,
) -> DiscoveryResult:
    """Run LLM discovery filter. Returns keepers plus whether rejects are trusted."""
    if not opportunities:
        return DiscoveryResult()
    if not discovery_enabled(project):
        ids = [str(o.get("target_id", "")) for o in opportunities if o.get("target_id")]
        return DiscoveryResult(
            keepers=list(opportunities),
            evaluated_ids=ids,
            skip_rejects=False,
        )

    cfg = project.get("opportunity_discovery") or {}
    min_dottie = float(cfg.get("min_dottie_score", 8))
    max_candidates = int(cfg.get("max_candidates", 12))
    max_results = int(cfg.get("max_results", 10))
    max_tokens = int(cfg.get("max_tokens", _DISCOVERY_MAX_TOKENS))
    thinking = bool(cfg.get("thinking", False))
    if thinking:
        if max_tokens < _THINKING_MIN_TOKENS:
            logger.warning(
                "Dottie discovery: thinking on with max_tokens=%s; "
                "raising to %s so the keeper JSON is not cut off",
                max_tokens,
                _THINKING_MIN_TOKENS,
            )
            max_tokens = _THINKING_MIN_TOKENS
        groq_extra = {
            "reasoning_effort": "default",
            "reasoning_format": "hidden",
        }
        json_mode_enabled = False
    else:
        groq_extra = {"reasoning_effort": "none"}
        json_mode_enabled = True


    # Prefer higher heuristic scores first as LLM context budget
    ranked = sorted(
        opportunities,
        key=lambda o: o.get("relevance_score", 0),
        reverse=True,
    )[:max_candidates]

    payload = []
    by_id = {}
    for opp in ranked:
        tid = str(opp.get("target_id", ""))
        if not tid:
            continue
        by_id[tid] = opp
        payload.append({
            "target_id": tid,
            "title": opp.get("title", ""),
            "subreddit": opp.get("subreddit", ""),
            "url": opp.get("url", ""),
            "body": (opp.get("body") or "")[:_BODY_CHARS],
            "keyword": opp.get("keyword", ""),
            "num_comments": opp.get("num_comments", 0),
            "post_score": opp.get("post_score", 0),
        })

    evaluated_ids = list(by_id.keys())
    if not payload:
        return DiscoveryResult(evaluated_ids=evaluated_ids, skip_rejects=False)

    system = (
        SYSTEM_PROMPT
        .replace("MIN_DOTTIE_SCORE", str(int(min_dottie)))
        .replace("MAX_RESULTS", str(max_results))
    )
    user_prompt = (
        "Evaluate these Reddit posts for Dottie. "
        "Return JSON only as {\"keepers\":[...]}.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    def _call(prompt: str, json_mode: bool = True) -> str:
        kwargs = {
            "prompt": prompt,
            "system_prompt": system,
            "task": "analytical",
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "extra_body": groq_extra,
        }
        if json_mode and json_mode_enabled:
            kwargs["response_format"] = _JSON_OBJECT
        return llm.generate(**kwargs)

    def _call_resilient(prompt: str) -> str:
        try:
            return _call(prompt, True)
        except Exception as e:
            err = str(e).lower()
            if "json_validate" in err or "failed to generate json" in err:
                logger.warning(
                    "Dottie discovery: Groq JSON mode rejected; retrying without json_object"
                )
                return _call(prompt, False)
            raise

    raw = ""
    try:
        raw = _call_resilient(user_prompt)
    except Exception as e:
        logger.error(f"Dottie discovery LLM failed: {e}")
        return DiscoveryResult(evaluated_ids=evaluated_ids, skip_rejects=False)

    parsed = _extract_json_array(raw)
    if parsed is None:
        logger.warning("Dottie discovery: retrying once for valid JSON")
        try:
            raw = _call_resilient(
                _RETRY_PROMPT + "\n\nPosts:\n" + json.dumps(payload, ensure_ascii=False)
            )
        except Exception as e:
            logger.error(f"Dottie discovery LLM retry failed: {e}")
            return DiscoveryResult(evaluated_ids=evaluated_ids, skip_rejects=False)
        parsed = _extract_json_array(raw)

    if parsed is None:
        logger.warning(
            "Dottie discovery: still unparseable after retry — skipping candidates "
            "(will not dump keyword hits onto the digest)"
        )
        return DiscoveryResult(
            keepers=[],
            evaluated_ids=evaluated_ids,
            skip_rejects=True,
        )

    kept: List[Dict] = []
    seen = set()
    for item in parsed:
        tid = str(item.get("target_id") or "")
        if not tid or tid not in by_id or tid in seen:
            continue
        dottie = float(item.get("dottie_score") or 0)
        if dottie < min_dottie:
            continue
        social = float(item.get("social_potential") or 0)
        community = float(item.get("community_growth") or 0)
        recurring = float(item.get("recurring_potential") or 0)
        final = item.get("final_score")
        try:
            final_f = float(final) if final is not None else _final_score(dottie, social, community)
        except (TypeError, ValueError):
            final_f = _final_score(dottie, social, community)

        base = dict(by_id[tid])
        base["dottie_score"] = dottie
        base["social_potential"] = social
        base["recurring_potential"] = recurring
        base["community_growth"] = community
        base["final_score"] = final_f
        # Primary sort key for queue / dashboard
        base["relevance_score"] = final_f
        base["activity_type"] = item.get("activity_type") or ""
        base["summary"] = item.get("summary") or ""
        base["group_size"] = item.get("group_size") or "3-8"
        base["difficulty"] = item.get("difficulty") or ""
        base["could_dottie_host"] = bool(item.get("could_dottie_host", True))
        base["why"] = item.get("why") or ""
        base["meetup_title"] = item.get("meetup_title") or ""
        base["meetup_description"] = item.get("meetup_description") or ""
        base["category"] = item.get("category") or ""
        base["urgency"] = item.get("urgency") or "This Week"
        base["discovery"] = "dottie_llm"
        kept.append(base)
        seen.add(tid)

    kept.sort(key=lambda o: o.get("final_score", 0), reverse=True)
    kept = kept[:max_results]
    logger.info(
        f"Dottie discovery: {len(payload)} candidates → {len(kept)} keepers "
        f"(min_dottie={min_dottie})"
    )
    return DiscoveryResult(
        keepers=kept,
        evaluated_ids=evaluated_ids,
        skip_rejects=True,
    )


def persist_discovery_results(
    db,
    all_candidates: List[Dict],
    result: DiscoveryResult,
    project_name: str,
) -> None:
    """Keepers stay pending with LLM scores. Skip rejects only when the parse is trusted."""
    keepers = result.keepers
    keep_ids = {str(k.get("target_id")) for k in keepers}
    for opp in keepers:
        tid = str(opp.get("target_id", ""))
        meta = {
            "keyword": opp.get("keyword"),
            "post_score": opp.get("post_score"),
            "num_comments": opp.get("num_comments"),
            "upvote_ratio": opp.get("upvote_ratio"),
            "discovery": "dottie_llm",
            "dottie_score": opp.get("dottie_score"),
            "social_potential": opp.get("social_potential"),
            "recurring_potential": opp.get("recurring_potential"),
            "community_growth": opp.get("community_growth"),
            "final_score": opp.get("final_score"),
            "activity_type": opp.get("activity_type"),
            "summary": opp.get("summary"),
            "meetup_title": opp.get("meetup_title"),
            "meetup_description": opp.get("meetup_description"),
            "category": opp.get("category"),
            "urgency": opp.get("urgency"),
            "why": opp.get("why"),
            "group_size": opp.get("group_size"),
            "could_dottie_host": opp.get("could_dottie_host"),
            "url": opp.get("url"),
        }
        db.log_opportunity(
            platform="reddit",
            target_id=tid,
            title=opp.get("title", ""),
            subreddit_or_query=opp.get("subreddit", ""),
            score=float(opp.get("final_score") or opp.get("relevance_score") or 0),
            project=project_name,
            status="pending",
            metadata=meta,
        )

    if not result.skip_rejects:
        return

    for opp in all_candidates:
        tid = str(opp.get("target_id", ""))
        if tid and tid not in keep_ids:
            db.update_opportunity_status(
                tid,
                "skipped",
                rejection_reason="dottie_discovery: below meetup bar",
            )
