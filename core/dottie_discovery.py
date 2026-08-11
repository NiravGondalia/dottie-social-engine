"""Dottie Opportunity Discovery — LLM filter for meetup-worthy Reddit posts.

Keyword scan casts a wide net. This module asks: would this thread naturally
become a real-world Dottie meetup in the next ~7 days?
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an Opportunity Discovery Engine for Dottie.

Dottie is a Social OS that helps people build real friendships by matching them into small, intentional, in-person groups.

Your job is NOT to find popular Reddit posts.
Your job is to find discussions that could become real-world activities inside Dottie.

GOAL
Only return posts that represent an activity people could realistically do together within the next 7 days.
Think: "People should meet because of this." NOT "People need information."

HIGH VALUE: sports/running/hiking/cycling/walking/pickleball/volleyball/tennis/badminton/soccer/basketball; coffee/brunch/restaurants/food festivals/farmers markets; concerts/live music/comedy/theatre/festivals/galleries/museums; language exchange/book clubs/board games/trivia/chess/coding/AI/startup networking/hackathons; volunteering/beach or park cleanups/community events; photography walks/sunset spots/picnics/dog walks; weekend plans; "I'm new in Toronto"; "looking for friends"; "anyone interested"; "who wants to join".

EXCLUDE forever: medical, healthcare, mental health, legal, government, taxes, immigration, housing, landlords, utilities, mechanics, repairs, cleaning, shopping, financial advice, insurance, tattoos, beauty, hair salons, pet services/cremation/vet, home services, customer support, complaints, rants, politics, crime, news, traffic, emergency reporting, product recommendations, dating/hookups, 1:1 only, private house parties with no public angle, already fully closed organized events.

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

QUALITY BAR: "If Dottie existed, would this Reddit thread naturally become a meetup?" If NO, omit it.

OUTPUT: Return ONLY a JSON array (no markdown). Each kept item:
{
  "target_id": "...",
  "title": "...",
  "subreddit": "...",
  "url": "...",
  "summary": "...",
  "activity_type": "...",
  "dottie_score": 10,
  "social_potential": 4,
  "recurring_potential": 3,
  "community_growth": 4,
  "final_score": 7.5,
  "group_size": "4-8",
  "difficulty": "Easy",
  "could_dottie_host": true,
  "why": "...",
  "meetup_title": "...",
  "meetup_description": "...",
  "category": "...",
  "urgency": "Today | This Week | Evergreen"
}
Omit rejects. Empty array [] if none qualify. Max MAX_RESULTS items, ranked by final_score desc.
"""


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    """Parse JSON array from LLM output (tolerates markdown fences)."""
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    # Find outermost array
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end < 0 or end <= start:
        return []
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Dottie discovery: failed to parse LLM JSON")
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


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
) -> List[Dict]:
    """Run LLM discovery filter. Returns enriched keepers only."""
    if not opportunities:
        return []
    if not discovery_enabled(project):
        return opportunities

    cfg = project.get("opportunity_discovery") or {}
    min_dottie = float(cfg.get("min_dottie_score", 8))
    max_candidates = int(cfg.get("max_candidates", 20))
    max_results = int(cfg.get("max_results", 10))

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
            "body": (opp.get("body") or "")[:400],
            "keyword": opp.get("keyword", ""),
            "num_comments": opp.get("num_comments", 0),
            "post_score": opp.get("post_score", 0),
        })

    if not payload:
        return []

    system = (
        SYSTEM_PROMPT
        .replace("MIN_DOTTIE_SCORE", str(int(min_dottie)))
        .replace("MAX_RESULTS", str(max_results))
    )
    user_prompt = (
        "Evaluate these Reddit posts for Dottie. Return JSON array of keepers only.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    try:
        raw = llm.generate(
            prompt=user_prompt,
            system_prompt=system,
            task="analytical",
            max_tokens=2500,
            temperature=0.2,
        )
    except Exception as e:
        logger.error(f"Dottie discovery LLM failed: {e}")
        # Fail open with empty — better than spam advice posts as "opportunities"
        return []

    kept: List[Dict] = []
    seen = set()
    for item in _extract_json_array(raw):
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
    return kept


def persist_discovery_results(db, all_candidates: List[Dict], keepers: List[Dict], project_name: str):
    """Update DB: keepers pending with new scores; rejects marked skipped."""
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

    for opp in all_candidates:
        tid = str(opp.get("target_id", ""))
        if tid and tid not in keep_ids:
            db.update_opportunity_status(
                tid,
                "skipped",
                rejection_reason="dottie_discovery: below meetup bar",
            )
