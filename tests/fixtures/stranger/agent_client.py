"""Stranger-test shape: an OpenAI agent client with a hardcoded key."""
import openai


def complete(prompt: str) -> str:
    client = openai.OpenAI(api_key="sk-proj-a1b2c3d4e5f6g7h8i9j0k1l2")
    response = client.completions.create(model="gpt-4o-mini", prompt=prompt)
    return response.choices[0].text
