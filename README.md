# Anti-Hallucination

**Your numbers decide; the AI only writes.**

A Python layer for any text an AI writes from data: a sales report, a monthly
metrics summary, a finance update, a summary of tickets or articles. Your code
computes the figures and decides the verdicts. The AI writes with placeholders
and never sees a value. Every sentence is checked against your data before it
goes out; a sentence that fails is dropped or replaced by one you wrote, never
repaired. Each decision is kept in a receipt you can verify and run again.

*Experimental (v0.2). The checks use only the Python standard library.*

## Install

Requires Python 3.11 or later.

```bash
pip install git+https://github.com/Jegoba90/anti-hallucination

# To let Claude write the drafts as well:
pip install "antihallucination[claude] @ git+https://github.com/Jegoba90/anti-hallucination"

# To use it from Claude Desktop, Claude Code or any MCP client:
pip install "antihallucination[mcp] @ git+https://github.com/Jegoba90/anti-hallucination"
```

## How it works

```python
from antihallucination import Fact, compose, verify

facts = [
    Fact("sales", 1250, unit="units", subject="sales"),
    Fact("sales_change", -3.2, unit="%", change=True, subject="sales"),
]

# The writer (any LLM, or a person) writes placeholders; Python writes the figures.
draft = "Sales fell {sales_change:abs} to {sales}. Next quarter will be better."
result = compose(draft, facts, locale="en")
print(result.text)
# Sales fell 3.2% to 1,250 units.

# A text someone already wrote, figures typed in, checked against the same facts.
report = verify("Sales grew 5% to 1,300 units.", facts, locale="en")
print([(finding.check, finding.span) for finding in report.findings])
# [('unbacked_number', '5%'), ('unbacked_number', '1,300'), ('direction_contradiction', 'grew')]
```

The forecast in the draft was dropped. `result.decisions` says why, sentence by
sentence, and `result.receipt` holds the inputs, each decision and a SHA-256
digest.

- `compose()` is for text you are about to publish: the writer uses
  placeholders (`{sales}`, `{sales_change:abs}`, `{sales_change:signed}`) and
  never types a figure.
- `verify()` is for text someone already wrote: every figure must match one of
  your facts at the precision written, or appear in a label or a source.
- `Label` and `classify()` hold verdicts your rules decided ("a slight
  decline"), so the writer places them instead of choosing them.
- `Source` holds a text the writer may summarize. A sentence that cites it as
  `[id]` may only state what that source says.
- `fallbacks` hold sentences you wrote. When a sentence about the same subject
  fails, yours goes out in its place.

## What it checks

| Check | `compose()` | `verify()` |
|---|---|---|
| Figures | The writer types none. A sentence that cites a source may copy that source's figures | Each figure is a fact rounded to the precision written, or appears in a label or a source |
| Signs and directions | «fell» or «cayeron» must agree with the sign of the change; a move with no change or source behind it is flagged | Same |
| Names | Each proper name must appear in your facts, labels, sources or `known_names` | Same |
| Forecasts, certainty, causes | Dropped by default, from word lists in Spanish and English | Same |
| Data in every sentence | A sentence must carry a placeholder or cite a source | A sentence must carry a figure or verdict from your data, a move checked against a change, or a citation |

Figures are read the way their language writes them: «1.250» is a thousand two
hundred and fifty in Spanish and one and a quarter in English, «1,2 millones»
and «4bn» carry their scale, and «tres» or «twenty-five» are figures too.

**What it can show:** no digit or numeric character (², ½, Ⅲ) in a composed
text was typed by the writer; each comes from your facts, labels and fallbacks,
or from the source its sentence cites. In a verified text, each figure written
in digits matches a fact or appears in a label or source. Numbers written in
words are caught from a list. Every sentence that goes out carries something
from your data or cites a source, whatever its words: «performance remains
within the expected parameters» carries nothing and is cut.

**What it cannot show:** that your facts are right, or that a sentence carrying
your data claims no more than it in words the lists do not contain («sales were
{sales}, a solid result»). Word lists only catch the phrasings they hold;
keeping verdicts in labels and figures in placeholders does not depend on them.
A name that opens a sentence is not checked. The receipt's digest is unkeyed:
it shows that a receipt is internally consistent, not who issued it.

## Let a model write

```python
from antihallucination import write
from antihallucination.writers import ClaudeWriter  # pip install "antihallucination[claude] @ ..."

written = write("A two-sentence sales summary for the board.", facts, writer=ClaudeWriter(), locale="en")
print(written.text)
```

The model is told each placeholder, what it measures, the shape Python will
write («N units») and which way each change went. It is never shown a value.
Its draft then goes through `compose()`. If a sentence fails, the model is asked
again with the reasons, still without values; the attempt with fewer failed
sentences goes out, and a sentence that still fails is dropped or replaced by
your fallback.

`ClaudeWriter` runs `claude-opus-5-5` through the Anthropic SDK, with the
server-side fallback on: if the model declines, the API runs the request again
on another model. `OpenAICompatibleWriter.openai(model)`, `.groq(model)` and
`.ollama(model)` cover OpenAI, Groq and local models. Any function that takes
`(system, prompt)` and returns text is a writer too.

## From the command line

```bash
antihallucination verify examples/saas/written_by_an_ai.txt --data examples/saas/data.json
antihallucination compose examples/saas/draft.txt --data examples/saas/data.json --receipt receipt.json
antihallucination receipt receipt.json --data examples/saas/data.json
antihallucination write --data examples/saas/data.json --brief "A short monthly update for the team."
```

`python -m antihallucination` works the same. The data file holds the facts,
labels, sources, fallbacks and known names; a label can be decided by
thresholds from a fact. [`antihallucination/data.py`](antihallucination/data.py)
documents its format. The exit status is 0 when every sentence passed, 1 when
some failed, 2 when the input cannot be read and 3 when the writer failed.

## Use it from Claude or any MCP client

No code needed: an assistant that speaks MCP writes the text, and the layer
writes every figure and checks every sentence before the text reaches you. The
server calls no model and no network, so your data stays on your machine.

Claude Code:

```bash
claude mcp add --transport stdio --scope user anti-hallucination -- python -m antihallucination.mcp_server
```

Claude Desktop, in `claude_desktop_config.json` (on Windows in
`%APPDATA%\Claude\`, on macOS in `~/Library/Application Support/Claude/`):

```json
{
  "mcpServers": {
    "anti-hallucination": {
      "command": "python",
      "args": ["-m", "antihallucination.mcp_server"]
    }
  }
}
```

Use the `python` you installed the package with (on macOS it may be
`python3`). The installed `antihallucination-mcp` command starts the same
server. Then give the assistant your figures and ask it to write with the
anti-hallucination tools:

| Tool | What it does |
|---|---|
| `prepare_report` | Gives the placeholders and the rules for a brief, without any figure |
| `compose_report` | Fills a draft written with placeholders, keeps the sentences that pass, and returns the text, why each sentence went out or not, and a receipt |
| `verify_text` | Checks a text that already has its figures |
| `check_receipt` | Verifies a receipt and runs its decision again |

The assistant has seen your figures, so here the guarantee is not that it never
saw them: it is that none of them reaches the text unless Python writes it.

## Examples

| Example | Language | What it shows |
|---|---|---|
| [`examples/saas/`](examples/saas) | English | Monthly SaaS metrics: invented figures and a forecast are replaced by your sentences |
| [`examples/support/`](examples/support) | English | A summary of support tickets: each sentence may only state what the ticket it cites says |
| [`examples/sales/`](examples/sales) | Spanish | A quarterly sales report, with a verdict decided by thresholds |
| [`examples/sales_report.py`](examples/sales_report.py) | Spanish | The same report from Python, with both modes and the receipt |

Each folder has a `data.json`, a text written with figures typed in
(`written_by_an_ai.txt`) and a draft with placeholders (`draft.txt`).

## Tested with a real model

On 2026-11-16 `openai/gpt-oss-120b`, on Groq, wrote four drafts of the Spanish
sales report. It typed no figure. In the first draft one sentence carried no
data, «El desempeño general se mantiene dentro de los parámetros esperados», and
passed every check; the rule that every sentence must carry data came from it,
and the three drafts after it kept all their sentences. The drafts are kept in
[`tests/fixtures/real_model/`](tests/fixtures/real_model) and judged on every
test run. Claude has not run against the live API yet. The record is in
[`docs/pruebas-2026-11-16.md`](docs/pruebas-2026-11-16.md).

## Where it comes from

This is the method of the engine behind [CryptoCapi](https://cryptocapi.com),
where the model writes one line per news note and Python writes every market
figure. [anti-hallucination-crypto-agent](https://github.com/Jegoba90/anti-hallucination-crypto-agent)
shows that engine's output and seals in a terminal.

## Development

```bash
pip install -e ".[dev]"
pytest
mypy .
ruff check .
```

MIT license.
