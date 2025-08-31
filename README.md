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

### Using `ai_mark`

If you want to use the AI marking helper directly in Python code, call `ai_mark` with the student's answer, reference text, and the student's level:

```python
from app import ai_mark

score, feedback = ai_mark("Ich bin ein Student", "Ich bin eine Studentin", "A1")
```

`score` will be an integer from 0–100 (or `None` if the OpenAI key is missing) and `feedback` is a short tutor-style message tailored to the specified student level.
