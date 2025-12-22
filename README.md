# Grammar Helper

This Streamlit app is used to review student submissions against reference answers.

The AI provides a single feedback block of roughly forty words, pointing out exact mistakes and reminding students to enter umlauted characters.

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

## Firestore support

The app can optionally store each saved row in a Firestore collection. To
enable this feature provide Firebase service account credentials in
`secrets.toml` under the `firebase` key:

```toml
[firebase]
type = "service_account"
project_id = "your-project-id"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "firebase-adminsdk@example.iam.gserviceaccount.com"
token_uri = "https://oauth2.googleapis.com/token"
```

When the credentials are available, the UI shows a checkbox labelled
“also save to Firestore” next to the save button. Checking it writes the data to
the `scores` collection in addition to the Google Sheet.

## Submission storage paths

Student submissions are kept in the client’s local storage beneath a
level- and student-specific path. When `submitFinalWork` runs, it saves the
entry into `store.submissions` and returns a path like
`submissions/{levelKey}/{studentKey}` (the level key is normalized and the
student key is built from the email plus student code). A lock record is also
created under `submission_locks/{studentKey}` to avoid duplicate submissions.

If `submitWorkToSpecificPath` is used, the submission is appended to
`store.submissions[levelKey].posts` using the explicit path provided, but the
data still lives under the `submissions/{levelKey}` branch in local storage.

