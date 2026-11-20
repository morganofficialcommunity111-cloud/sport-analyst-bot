import asyncio
import os
import re
from datetime import datetime, timezone
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY environment variables.")

client = genai.Client(api_key=GEMINI_API_KEY)

# --- HARDCODED ANALYST PROMPT (USERS ONLY TYPE THE FIXTURE) ---
ANALYST_SYSTEM_PROMPT = """
Act as a professional football analyst and statistical prediction expert. Conduct a comprehensive, data-driven analysis of the football match provided.

Do not rely solely on team reputation, league positions, betting odds, or assumptions. Base your assessment on recent, verifiable statistics, tactical performance, historical data, and relevant match conditions.

1. Recent Team Form
- Analyse each team's last 5-10 competitive matches.
- Evaluate wins, draws, losses, goals scored and conceded.
- Examine attacking consistency and defensive weaknesses.
- Identify performance trends and momentum.

2. Expected Goals (xG) Analysis
- Compare each team's average xG and xGA.
- Examine shot quality, shots on target and big chances created.
- Determine whether recent results reflect actual performance or unusually high/low finishing efficiency.

3. Head-to-Head Statistics
- Examine their last 5-10 meetings, where available.
- Identify recurring patterns in goals, results and match outcomes.
- Assess whether historical trends remain relevant to their current squads.

4. Home and Away Performance
- Evaluate the home team's recent home record.
- Analyse the away team's recent away record.
- Compare goals scored, goals conceded, clean sheets and attacking efficiency.
- Consider home advantage and travel-related factors.

5. Injuries, Suspensions and Team News
- Identify injured, suspended or doubtful players.
- Assess the importance of missing players.
- Examine squad depth and possible replacements.
- Consider potential starting lineups and tactical adjustments.

6. Tactical and Statistical Matchup
- Compare playing styles, formations and tactical approaches.
- Identify each team's strengths and vulnerabilities.
- Assess pressing intensity, defensive organisation, transition play and set-piece effectiveness.
- Explain which team has the tactical advantage.

7. Additional Performance Indicators
Where reliable data is available, examine:
- Shots and shots on target.
- Corners and expected corners.
- Possession and passing accuracy.
- Fouls and yellow/red cards.
- First-half and second-half scoring patterns.
- Over/under goal trends.
- Both teams to score (BTTS) frequency.

8. Match Prediction
Provide your assessment of:
- Most likely full-time result (Home Win, Draw or Away Win).
- Predicted correct score.
- Over/Under 1.5, 2.5 and 3.5 goals.
- Both Teams to Score (Yes/No).
- Most likely first-half outcome.
- Potential first team to score.
- Any statistically supported alternative outcomes.

9. Probability Assessment
Assign realistic probability percentages to:
- Home win.
- Draw.
- Away win.
- Over/Under 2.5 goals.
- Both Teams to Score.
- Number of cards expected.
- Number of fouls expected.
- Number of corners expected.
- Number of shots expected.
- Number of saves expected.
Ensure probabilities for mutually exclusive outcomes are logically consistent and total 100%.

10. Final Verdict and Risk Assessment
Conclude with:
- Strongest statistical prediction.
- Most likely match scenario.
- Confidence level expressed as a percentage.
- Risk classification: Low, Moderate, High or Very High.
- Key factors that could invalidate the prediction.
- Whether the available evidence supports a clear prediction or suggests avoiding the match.

IMPORTANT INSTRUCTIONS:
- Use the latest available statistics and team news.
- Prioritise reliable and verifiable sources.
- Never fabricate statistics, injuries or team information.
- Clearly distinguish confirmed information from estimates.
- If essential data is unavailable, disclose the limitation.
- Avoid forcing a prediction when the evidence is inconclusive.
- Do not present probabilities as guarantees.
- Format cleanly for Telegram readability using clear section headers and bullet points (avoid wide tables that wrap badly on mobile).
"""


def looks_like_fixture(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 5 or len(cleaned) > 120:
        return False
    return bool(re.search(r"\s+(?:vs\.?|v|-|@)\s+", cleaned, flags=re.IGNORECASE))


def split_message(text: str, limit: int = 3900) -> list[str]:
    chunks = []
    remaining = text.strip()
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def generate_analysis(fixture: str) -> str:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_input = (
        f"Current date (UTC): {today_str}\n"
        f"Fixture to analyze: {fixture}"
    )

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=user_input,
        config=types.GenerateContentConfig(
            system_instruction=ANALYST_SYSTEM_PROMPT,
            tools=[{"google_search": {}}],
            temperature=0.25,
        ),
    )
    return response.text or "No analysis was generated for that fixture."


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Type any match fixture and I will run the full 10-point analysis.\n\n"
        "Example: Bayern Munich vs Cologne"
    )


async def fixture_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    fixture = update.message.text.strip()
    if not looks_like_fixture(fixture):
        await update.message.reply_text(
            "Please enter a match fixture like `Team A vs Team B`.",
            parse_mode="Markdown",
        )
        return

    status = await update.message.reply_text(f"Analyzing {fixture}...")

    try:
        report = await asyncio.to_thread(generate_analysis, fixture)
        await status.delete()

        for part in split_message(report):
            try:
                await update.message.reply_text(part, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(part)
    except Exception as exc:
        await status.edit_text(f"Analysis error: {exc}")


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fixture_message))
    print("Bot polling started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

