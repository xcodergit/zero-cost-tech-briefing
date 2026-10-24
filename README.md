# Zero-Cost Tech Briefing Bot

A no-paid-API GitHub Actions project that collects recent technology headlines from RSS feeds, creates a short narrated vertical video, and saves it as a downloadable workflow artifact for review.

## What this project does

- Runs daily on GitHub Actions, or on demand.
- Reads public RSS feeds; no news API key is required.
- Filters old items and removes duplicate headlines.
- Creates a short, template-based briefing from up to three stories.
- Uses `espeak-ng` for local text-to-speech (no TTS API).
- Generates original 1080×1920 graphic cards with captions using Pillow.
- Uses FFmpeg to render an MP4.
- Uploads the MP4, source list, and script as a workflow artifact retained for 7 days.

## Important honest limitations

- **No paid services, API keys, or credit card are required.**
- This first version does **not** call a large language model. The script is template-based so it can run without a model API or expensive local model. It does not invent details, but the writing is less sophisticated than a strong editor or LLM.
- `espeak-ng` voice quality is understandable but robotic. The video uses original graphic cards rather than licensed stock footage, which avoids footage API and licensing dependencies.
- RSS summaries can be incomplete or wrong. Always review the MP4 and source list before publishing. This project does not auto-publish.
- GitHub Actions scheduled runs are best-effort and can be delayed. The schedule is UTC.
- For the most predictable zero-cost hosted runs, use a **public GitHub repository** and standard GitHub-hosted runners. Public source code is visible to everyone. Do not add secrets; this project needs none.
- Artifacts expire after 7 days. Download them if you want to keep them. GitHub limits and policies can change; no service can be guaranteed free forever.

## One-time setup

1. Create a new **public** repository on GitHub, e.g. `zero-cost-tech-briefing`.
2. Upload the contents of this project into the repository root. Keep `.github/workflows/daily-video.yml` in that exact location.
3. Open **Actions** in the repository. If GitHub asks, enable workflows.
4. Open **Daily tech briefing video** and select **Run workflow** to test it.
5. Wait for the run to finish. Open the completed run, find **Artifacts**, and download `tech-briefing-video`.
6. The downloaded ZIP contains `tech_briefing.mp4`, `sources.json`, and `script.txt`.

After the initial test, the workflow is scheduled daily at 12:20 UTC (17:50 India Standard Time). You do not need to leave your PC running.

## Customization

Edit `config.json` to change the feed list, freshness window, story count, or schedule. The schedule itself is in `.github/workflows/daily-video.yml`.

### RSS feeds included

- TechCrunch AI: `https://techcrunch.com/category/artificial-intelligence/feed/`
- Ars Technica: `https://feeds.arstechnica.com/arstechnica/index`
- Hacker News front page: `https://hnrss.org/frontpage`

A feed may occasionally be unavailable or change its URL. The collector logs feed errors and continues with the others. Add or remove feeds in `config.json`.

## Quality and accuracy safeguards

- The collector filters by publication date when a feed supplies one.
- It deduplicates by normalized title.
- The video shows the story headline and a short excerpt, plus a source domain.
- Source URLs and timestamps are written to `sources.json`.
- The generator exits with an error instead of fabricating a story if no recent stories can be collected.

## Troubleshooting

- **No artifact:** Open the run logs. If every feed is unavailable or has no recent items, the job intentionally fails rather than creating a fake news video. Run again later or adjust `max_age_hours` in `config.json`.
- **A feed fails:** This is normal; other feeds are still used. If all feeds fail, verify their URLs.
- **Workflow does not run at the exact time:** Scheduled GitHub Actions can be delayed, especially during high load.
- **Need a better voice:** This no-card version uses `espeak-ng`. Better hosted neural TTS generally depends on a provider or local model and more setup/resources.
- **Want a more intelligent script:** A local LLM can be added later, but GitHub-hosted runners are not designed for reliably running large models. This starter deliberately avoids that dependency.

## License

The code is provided under the MIT License. Feed content remains subject to each publisher's terms. This project does not download or redistribute article images or full articles.
