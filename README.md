# BlogForge AI

BlogForge AI is a Streamlit app that researches a topic and drafts a structured technical blog post with LangGraph and Google Gemini. Search-backed research and generated images are optional; the app can write a draft without either feature.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- A Google AI API key (`GOOGLE_API_KEY`)
- A Tavily API key (`TAVILY_API_KEY`) for web research (optional)

## Setup

```bash
uv sync
cp .env.example .env
```

Add your Google AI key to `.env`. Add a Tavily key to enable web search. Keep `.env` private; it is excluded from Git.

## Run

```bash
uv run streamlit run frontend.py
```

The app saves generated Markdown drafts in the working directory and generated images under `images/`.

## Configuration and data

The topic and writing prompts are sent to Google Gemini. When Tavily is configured, research queries are sent to Tavily and returned source material is used to ground the draft. Image generation uses the Google GenAI API when the generated plan requests images.

Copy `.env.example` to `.env` and provide:

```dotenv
GOOGLE_API_KEY=your_google_ai_api_key
TAVILY_API_KEY=your_tavily_api_key
```

`TAVILY_API_KEY` is optional. Do not commit real API keys or generated content containing private information.
