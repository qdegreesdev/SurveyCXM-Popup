import json
from openai import OpenAI
from loguru import logger
from config import settings

def generate_review_suggestion(survey_summary: list) -> str:
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        logger.warning("No valid OpenAI API key — using fallback review suggestion.")
        return "Thank you for your feedback. We appreciate your suggestions for improvement."

    try:
        client = OpenAI(api_key=settings.openai_api_key)

        # Prepare context from survey summary
        qa_text = "\n".join([f"Q{item['sequence']}: {item['question']}\nA: {item['answer']}" for item in survey_summary])

        prompt = f"""
You are an expert copywriter.
Based on the following survey questions and answers provided by a customer, generate a short review suggestion (under 35 words).
The review MUST be written from the user's perspective (first-person, using "I", "my") as if they are writing a final review to post online.
It should naturally summarize their overall sentiment and key feedback from the answers.

SURVEY RESPONSES:
{qa_text}
"""

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100,
        )

        suggestion = response.choices[0].message.content.strip()
        return suggestion

    except Exception as e:
        logger.error(f"Review suggestion AI error: {e}")
        return "Thank you for your feedback. We appreciate your suggestions for improvement."
