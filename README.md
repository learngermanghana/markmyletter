# Grammar Helper

This Streamlit app is used to review student submissions against reference answers.

## Configuration

Settings can be supplied through `streamlit` secrets or environment variables.

- `ANSWER_SOURCE`: preselects the reference answer source. Valid options are `"json"` or `"sheet"`.
  If not set, the app picks whichever source is available.

Example `secrets.toml` entry:

```toml
ANSWER_SOURCE = "json"
```

Or via environment variable:

```bash
export ANSWER_SOURCE=sheet
```

Run the app with:

```bash
streamlit run app.py
```

## AI scoring rubric

When the optional OpenAI key is supplied, the app can request an AI generated
assessment of a student's answer. The AI returns a JSON object with four
criteria—grammar, vocabulary, content and structure—each scored from 0 to 25.
The app sums these to produce the final 0‑100 score and shows the per‑criterion
breakdown in the interface. If the AI response cannot be parsed, the app falls
back to an error message and leaves the score at 0 so you can mark manually.
