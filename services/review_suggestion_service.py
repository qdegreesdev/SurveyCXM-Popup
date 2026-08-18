import json
from openai import OpenAI
from loguru import logger
from config import settings

def generate_review_suggestion(survey_summary: list) -> list:
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        logger.warning("No valid OpenAI API key — using fallback review suggestion.")
        return [
            "Thank you for your feedback. We appreciate your suggestions for improvement.",
            "Thanks for taking the time to share your thoughts with us. We value your input.",
            "Your feedback is incredibly helpful for us to continue improving our services."
        ]

    try:
        client = OpenAI(api_key=settings.openai_api_key)

        # Prepare context from survey summary
        qa_text = "\n".join([f"Q{item['sequence']}: {item['question']}\nA: {item['answer']}" for item in survey_summary])

        prompt = f"""
You are an expert copywriter.
Based on the following survey questions and answers provided by a customer, generate EXACTLY 3 distinct review suggestions (each under 15 words).
The reviews MUST be written from the user's perspective (first-person, using "I", "my") as if they are writing a final review to post online.
They should naturally summarize their overall sentiment and key feedback from the answers, with slight variations in tone or focus.
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
        return [
            "Thank you for your feedback. We appreciate your suggestions for improvement.",
            "Thanks for taking the time to share your thoughts with us. We value your input.",
            "Your feedback is incredibly helpful for us to continue improving our services."
        ]
