"""Read a photographed bet slip with Claude and return the bets on it.

The result only pre-fills a form: the punter checks and corrects it before
anything is saved.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

import anthropic

MODEL = os.getenv("SLIP_MODEL", "claude-opus-5-5")
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Claude's per-image limit
MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

SYSTEM = """You read photos and screenshots of Australian bookmaker bet slips \
(Sportsbet, TAB, Ladbrokes, Neds, Bet365 and similar) for a punting club, and \
list every bet on the slip.

For each bet:
- stake: the total amount the punter paid for that bet, in dollars. For each-way \
bets this is both halves together (a $15 each-way bet is 30). For bonus bets it \
is the bonus bet amount.
- description: a short summary in the club's style, e.g. "W Snitzel Dancer R7 \
Randwick", "P Polymnia", "NRL SGM 3 legs", "Multi 2 legs", "Box Trifecta SR7", \
"Harry Grant Clive Churchill Medal". Start win/place bets with W/P/EW.
- odds: the odds or price as shown, e.g. "$4.50", "$12.17", "tote", "104%". \
Empty string if the slip shows none.
- bonus: true only if the slip shows it was paid with a bonus bet, bonus cash or \
a promo token rather than the punter's money.

A multi or same-game multi is one bet, not one per leg. Ignore cash-out offers, \
account balances, adverts and anything that is not a placed bet. If the image is \
not a bet slip, set is_bet_slip to false and return no bets. Use note for anything \
the punter should double-check (blurry figures, a cut-off slip), else an empty string."""

SCHEMA = {
    "type": "object",
    "properties": {
        "is_bet_slip": {"type": "boolean"},
        "bets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stake": {"type": "number"},
                    "description": {"type": "string"},
                    "odds": {"type": "string"},
                    "bonus": {"type": "boolean"},
                },
                "required": ["stake", "description", "odds", "bonus"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["is_bet_slip", "bets", "note"],
    "additionalProperties": False,
}


class SlipReadError(Exception):
    """Something the punter should be told; they can still enter the bet by hand."""


@dataclass
class SlipBet:
    stake: float
    description: str
    odds: str
    bonus: bool


@dataclass
class SlipReading:
    bets: list[SlipBet]
    note: str


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def read_slip(image: bytes, media_type: str, client: anthropic.Anthropic | None = None) -> SlipReading:
    if media_type not in MEDIA_TYPES:
        raise SlipReadError("That file isn't a photo we can read - use a JPEG or PNG.")
    if len(image) > MAX_IMAGE_BYTES:
        raise SlipReadError("That photo is too large - try a screenshot instead.")

    client = client or anthropic.Anthropic(timeout=60.0)
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            # If the model declines, the API re-runs the request on a fallback model
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type,
                        "data": base64.standard_b64encode(image).decode(),
                    }},
                    {"type": "text", "text": "List the bets on this slip."},
                ],
            }],
        )
    except anthropic.AuthenticationError:
        raise SlipReadError("Slip scanning isn't set up correctly (bad API key) - tell the club admin.")
    except anthropic.RateLimitError:
        raise SlipReadError("Slip scanning is busy right now - try again in a minute.")
    except anthropic.APIStatusError as e:
        raise SlipReadError(f"Couldn't read the slip (error {e.status_code}) - try again or enter it by hand.")
    except anthropic.APIConnectionError:
        raise SlipReadError("Couldn't reach the slip reader - try again or enter it by hand.")

    if response.stop_reason == "refusal":
        raise SlipReadError("The slip reader couldn't process that image - enter the bet by hand.")
    if response.stop_reason == "max_tokens":
        raise SlipReadError("That slip has too much on it to read - enter the bets by hand.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise SlipReadError("Couldn't make sense of the slip - try a clearer photo.")
    if not data.get("is_bet_slip") or not data.get("bets"):
        raise SlipReadError("That doesn't look like a bet slip - try a clearer photo or screenshot.")
    bets = [
        SlipBet(round(float(b["stake"]), 2), b["description"].strip(), b["odds"].strip(), bool(b["bonus"]))
        for b in data["bets"]
    ]
    return SlipReading(bets=bets, note=data.get("note", "").strip())
