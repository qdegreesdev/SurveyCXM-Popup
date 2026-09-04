from typing import Optional
import json
from openai import OpenAI
from loguru import logger
from config import settings

def extract_nps_score(survey_summary: list, explicit_nps: Optional[int] = None) -> Optional[int]:
    if explicit_nps is not None:
        try:
            score = int(explicit_nps)
            if 0 <= score <= 10:
                return score
        except (ValueError, TypeError):
            pass

    for item in survey_summary:
        if not isinstance(item, dict):
            continue

        # Check direct keys in item dict
        for key in ("nps", "nps_score", "rating", "score","NPS"):
            if key in item and item[key] is not None:
                try:
                    val = int(item[key])
                    if 0 <= val <= 10:
                        return val
                except (ValueError, TypeError):
                    pass

        # Check question & answer content
        question = str(item.get("question", "")).lower()
        answer = str(item.get("answer", "")).strip()

        if any(k in question for k in ("nps", "recommend", "rate", "rating", "satisfaction")):
            try:
                first_part = answer.split("/")[0]
                digits = "".join([c for c in first_part if c.isdigit()])
                if digits:
                    val = int(digits)
                    if 0 <= val <= 10:
                        return val
            except (ValueError, TypeError):
                pass

    return None

def get_fallback_suggestions(nps_score: Optional[int] = None) -> list:
    if nps_score is not None:
        if nps_score >= 9:
            return [
                "Great experience overall! Highly satisfied with the prompt service and quality.",
                "Loved the service! Quick support and great results across the board.",
                "Extremely happy with my experience and would definitely recommend to others."
            ]
        elif nps_score >= 7:
            return [
                "Good service overall, though there is still some room for minor improvements.",
                "Satisfied with the experience, but hope to see faster response times in the future.",
                "Decent experience. Met most expectations with a few small areas to polish."
            ]
        else:
            return [
                "The service needs improvement. Experienced delays and expected a smoother process.",
                "Not fully satisfied with the experience. Hope key issues are addressed soon.",
                "Disappointed with aspects of the service. Clear improvements are needed going forward."
            ]
    return [
        "Thank you for your feedback. We appreciate your suggestions for improvement.",
        "Thanks for taking the time to share your thoughts with us. We value your input.",
        "Your feedback is incredibly helpful for us to continue improving our services."
    ]

def generate_review_suggestion(survey_summary: list, nps_score: Optional[int] = None) -> list:
    resolved_nps = extract_nps_score(survey_summary, nps_score)

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        logger.warning("No valid OpenAI API key — using fallback review suggestion.")
        return get_fallback_suggestions(resolved_nps)

    try:
        client = OpenAI(api_key=settings.openai_api_key)

        # Prepare context from survey summary
        qa_text = "\n".join([f"Q{item['sequence']}: {item['question']}\nA: {item['answer']}" for item in survey_summary])

        nps_info = ""
        if resolved_nps is not None:
            if resolved_nps >= 9:
                nps_category = f"Promoter (Score: {resolved_nps}/10)"
                tone_instruction = "The customer is a PROMOTER (high satisfaction). Generate enthusiastic, highly positive reviews praising the service."
            elif resolved_nps >= 7:
                nps_category = f"Passive (Score: {resolved_nps}/10)"
                tone_instruction = "The customer is PASSIVE (moderate satisfaction). Generate balanced, mildly positive reviews acknowledging pros while noting minor feedback."
            else:
                nps_category = f"Detractor (Score: {resolved_nps}/10)"
                tone_instruction = "The customer is a DETRACTOR (dissatisfied/low score). Generate critical, constructive reviews reflecting their concerns and areas needing improvement."
            nps_info = f"\nCUSTOMER NPS RATING: {nps_category}\nTONE INSTRUCTION: {tone_instruction}\n"

        prompt = f"""
You are an expert copywriter.
Based on the following survey questions, customer answers, and customer NPS rating, generate EXACTLY 3 distinct review suggestions (each under 18 words).
The reviews MUST be written from the user's perspective (first-person, using "I", "my") as if they are writing a final review to post online.
They should naturally reflect their overall sentiment and key feedback from the answers, strictly aligned with their NPS rating and tone:
- For Promoters (NPS 9-10): Enthusiastic, highly positive reviews praising the experience.
- For Passives (NPS 7-8): Balanced, neutral/positive reviews with constructive notes.
- For Detractors (NPS 0-6): Critical, constructive reviews highlighting dissatisfaction or areas needing improvement.
{nps_info}
Provide the output strictly as a JSON object with a single key "suggestions" containing an array of the 3 string suggestions.

SURVEY RESPONSES:
{qa_text}
"""

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content.strip()
        data = json.loads(content)
        suggestions = data.get("suggestions", [])

        # Fallback if the AI didn't return exactly a list
        if not isinstance(suggestions, list) or len(suggestions) == 0:
            raise ValueError("AI did not return a valid list of suggestions")

        return suggestions[:3]

    except Exception as e:
        logger.error(f"Review suggestion AI error: {e}")
        return get_fallback_suggestions(resolved_nps)

