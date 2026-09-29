# Editing the website wording

Start with **[`web/index.html`](../web/index.html)**. It contains most of the headings, descriptions, button text and methodology. You do not need to change a model prompt to make the website sound more like you.

## Find the text you want to change

Open the file in your editor and search for the words currently on the website. Turn on **word wrap** if a line runs off the screen.

| Website area | File | Search for |
|---|---|---|
| Browser title and search description | `web/index.html` | `<title>` or `name="description"` |
| Sidebar name, navigation and strapline | `web/index.html` | `Open Finance`, `Forecast lab`, `PUBLIC DATA. OPEN METHODS.` |
| Overview heading and introduction | `web/index.html` | `The macro picture.` |
| Forecast card on the overview | `web/index.html` | `one step ahead.` |
| Forecast page headings | `web/index.html` | `PREDICTIONS, WITH PERSPECTIVE`, `THE HONEST RESULT` |
| Question form and example questions | `web/index.html` | `What would you like to understand?`, `data-question=` |
| Empty answer panel | `web/index.html` | `Follow the evidence.` |
| Methodology headings and paragraphs | `web/index.html` | `Nothing behind the curtain.`, `01 / THE DATA` |
| Footer | `web/index.html` | `Source-led. Reproducible. Open.` |

For a simple wording change, edit only the text between the tags. For example:

```html
<h1 id="overview-title">The macro picture.</h1>
```

can become:

```html
<h1 id="overview-title">UK economic indicators</h1>
```

Keep the `id`, `class`, `href` and other attributes intact: they connect the text to navigation, styling and page behaviour. An exception is an example question: its `data-question="..."` attribute is the question submitted when clicked, so update that as well as its visible button label when changing the example.

## Text that appears after data loads

[`web/app.js`](../web/app.js) supplies dynamic labels and messages. Search within these functions:

| Function | Wording it controls |
|---|---|
| `setView` | Breadcrumb labels and browser titles for each page |
| `api` | Connection, timeout and request error messages |
| `renderForecast` | Forecast dates, comparison wording and interval-coverage labels |
| `readableMode` | Labels explaining generated answers, extraction and abstention |
| `renderAnswer` | Answer headings, source labels and retrieval-score explanations |
| `askQuestion` | Loading, validation, retry and submit-button text |
| `healthCheck` | Service online/unavailable labels |

Change quoted text, leaving variables such as `${forecast.value}` and the surrounding JavaScript intact. HTML text that says “Loading…” is usually replaced here. For example, if you rename **Find evidence**, change the button in `index.html` and its reset text in `askQuestion` so the old wording does not return after an answer.

[`web/styles.css`](../web/styles.css) controls colours, spacing and typography. It is not the main place to edit wording.

## The model prompt is separate

[`src/ofi/rag.py`](../src/ofi/rag.py) contains the generation instructions in `_generate`. Those instructions affect answers to users’ questions, not the website headings or branding. Leave the citation, evidence and abstention instructions in place when making cosmetic edits.

Forecast numbers, evaluation results, source excerpts and data caveats come from the underlying data and artifacts. Keep their meaning accurate when rewording the interface.

## Edit on GitHub and publish

1. Open [`web/index.html` on GitHub](https://github.com/shrut10/open-finance-intelligence/blob/main/web/index.html).
2. Click the pencil icon, find the wording and edit it.
3. Choose **Commit changes**, give the edit a short description, and commit to **main**.
4. The connected Vercel Git deployment builds and publishes commits to `main`. Wait for the deployment to show **Ready**, then refresh the [live website](https://open-finance-intelligence.vercel.app).

GitHub Actions runs the repository checks separately. If a deployment fails, the preceding successful version remains live; inspect the failed deployment before making more changes. To undo a wording edit, restore the previous text and commit again.

## Preview locally first

From the project folder, use the existing environment:

```bash
source .venv/bin/activate
python -m uvicorn app:app --reload --port 8000 --no-access-log
```

Open `http://localhost:8000`. Save your edits and refresh the browser; HTML, CSS and JavaScript edits do not require rebuilding the data or retraining the model. Check each page you changed, including its mobile layout. If you edit JavaScript, also run:

```bash
node --check web/app.js
```

Local changes only reach the public website after you commit and push them to `main`. See the [README](../README.md#run-locally) if the local environment has not been created yet.
