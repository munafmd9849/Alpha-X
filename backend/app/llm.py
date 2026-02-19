"""LLM Explanation Layer - explains ONLY, never decides.

Strict guardrails to prevent hallucination.
"""

import json
import logging
from typing import List, Optional

from app.models import LLMExplanation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a pharmacogenomics clinical assistant with ABSOLUTE constraints:
1. NEVER determine or suggest risk levels
2. ONLY explain the provided data
3. ALWAYS cite the exact variant detected
4. If unsure, say 'Consult clinical pharmacist'
5. Keep explanations under 100 words
6. Use lay terms but include mechanism"""

FALLBACK_RESPONSE = LLMExplanation(
    summary="Unable to generate AI explanation. Based on CPIC guidelines, this genotype indicates significant drug interaction risk.",
    mechanism="Consult clinical decision support tool for detailed mechanism.",
    citation="CPIC Guidelines",
)


def get_llm_explanation(
    drug: str,
    gene: str,
    diplotype: str,
    phenotype: str,
    risk: str,
    variants: List[str],
    recommendation: str,
) -> Optional[LLMExplanation]:
    """Get LLM explanation. Returns fallback on failure."""
    try:
        from app.config import get_settings
        settings = get_settings()

        if not settings.openai_api_key and not getattr(settings, "anthropic_api_key", None):
            return FALLBACK_RESPONSE

        input_data = {
            "drug": drug,
            "gene": gene,
            "diplotype": diplotype,
            "phenotype": phenotype,
            "risk": risk,
            "variants": variants,
            "recommendation": recommendation,
        }
        user_prompt = f"""Based on this pharmacogenomic data (DO NOT determine risk - it is already {risk}), provide a brief explanation:

{json.dumps(input_data, indent=2)}

Return a JSON object with exactly these keys: summary, mechanism, citation.
- summary: Brief lay explanation (under 100 words)
- mechanism: How the gene affects the drug
- citation: "CPIC Guideline for [Drug] and [Gene] (2023)"
"""

        if settings.openai_api_key:
            return _call_openai(user_prompt)
        if settings.anthropic_api_key:
            return _call_anthropic(user_prompt)

        return FALLBACK_RESPONSE

    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return FALLBACK_RESPONSE


def _call_openai(user_prompt: str) -> LLMExplanation:
    """Call OpenAI API."""
    from openai import OpenAI
    from app.config import get_settings
    client = OpenAI(api_key=get_settings().openai_api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=300,
    )
    content = resp.choices[0].message.content
    return _parse_llm_response(content)


def _call_anthropic(user_prompt: str) -> LLMExplanation:
    """Call Anthropic API."""
    from anthropic import Anthropic
    from app.config import get_settings
    client = Anthropic(api_key=get_settings().anthropic_api_key)
    msg = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    content = msg.content[0].text
    return _parse_llm_response(content)


def _parse_llm_response(content: str) -> LLMExplanation:
    """Parse LLM response into LLMExplanation. Use fallback on parse failure."""
    try:
        # Extract JSON from response (may have markdown code block)
        text = content.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        data = json.loads(text)
        return LLMExplanation(
            summary=data.get("summary", FALLBACK_RESPONSE.summary),
            mechanism=data.get("mechanism", FALLBACK_RESPONSE.mechanism),
            citation=data.get("citation", FALLBACK_RESPONSE.citation),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("LLM response parse failed: %s", e)
        return FALLBACK_RESPONSE
