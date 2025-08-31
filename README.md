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

## Editing rubric feedback

The AI now produces separate feedback for each rubric criterion (grammar and vocabulary).
Each comment is displayed in its own text area so instructors can review and edit before
saving. When saved, the comments are combined into the overall `comments` field and also
stored individually (e.g., `comment_grammar`, `comment_vocabulary`).
