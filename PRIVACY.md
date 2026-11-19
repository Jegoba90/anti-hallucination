# Privacy policy

Updated: 2026-11-19

This policy describes data handling in the Anti-Hallucination open-source
Python package, command line, MCP server, and self-hosted HTTP service. It
does not cover CryptoCapi or services run by other operators. The project
does not provide a hosted report-processing service through this repository.

## Data processed and why

The software processes the brief, draft or finished text, facts, labels,
source documents, fallbacks, rules, locale, and receipts you supply. It uses
them to prepare writing instructions, fill placeholders, check sentences,
and verify or replay receipts. Inputs can contain personal or confidential
information; supply only what you intend the selected client and deployment
to process.

## Local checks and MCP

The checking functions (`compose`, `verify`, and `replay`) and the four MCP
tools (`prepare_report`, `compose_report`, `verify_text`, and `check_receipt`)
process data on the machine running the software. These operations do not
call model providers or send data to the project maintainer. The MCP tools
return their results to the calling client and do not read or write user
files. The command line reads the input files you select or standard input.

An MCP client may already have sent your data to its model provider before
calling a tool. Tool responses can also enter the client's conversation,
history, or logs. The client's and model provider's privacy and retention
policies apply independently.

## Optional model writers

Calling `write()` with a provider writer, or using the CLI `write` command,
sends writing instructions and a prompt to the writer you select. The prompt
includes the brief, fact names and descriptions, units and change directions,
label text, and supplied source titles and full source text. Retries can
include the previous draft and feedback about failed checks.

Fact values are replaced with placeholders in the writer prompt, but this is
not anonymization: the brief, labels, source text, names, or other text you
provide can still disclose figures and sensitive information.

| Writer | Destination |
|---|---|
| OpenAI preset | `https://api.openai.com/v1/chat/completions` |
| Groq preset | `https://api.groq.com/openai/v1/chat/completions` |
| Ollama preset | `http://localhost:11434/v1/chat/completions` |
| Claude writer | Anthropic through its SDK, or the client you provide |
| Custom OpenAI-compatible URL or writer | The endpoint or callable you configure |

These are optional integrations, not outbound calls made by the four MCP
tools. Provider credentials come from explicit configuration, environment
variables, or the provider SDK's credential configuration. The OpenAI-compatible
writer sends its configured key as an authorization header to its configured
endpoint, including when you override the base URL. Choose that endpoint
accordingly. The project does not receive those keys. Provider and SDK
policies govern their own processing, retention, and any training use.

## Self-hosted HTTP service

Requests and responses travel between the caller and the host you operate.
The service runs the same checks without calling a model provider. It does
not maintain a database or report history. Data is processed in application
and worker memory; this is not a guarantee of secure memory erasure.

The operator controls the host, authentication token, TLS termination,
network access, and logging. Uvicorn, reverse proxies, containers, operating
systems, and monitoring tools may retain request metadata or other logs.
The service speaks HTTP; use TLS at the proxy when the network is not trusted.
Obtain any additional privacy and retention terms from the deployment operator.

## Outputs, receipts, and retention

The package has no built-in usage analytics, telemetry reporting, or training
pipeline. It does not send reports to the maintainer or retain a central copy.
It does not automatically save report contents to disk; the CLI prints
results and saves a receipt when you specify `--receipt`. Your application,
shell redirection, MCP client, or hosting infrastructure may save outputs.
Provider errors returned to the caller can contain provider-supplied text.

Receipts contain the input text, fact values and metadata, labels, fallbacks,
rules, sentence decisions, output text, and writer identification. Source
records keep identifiers, names, titles, and hashes instead of full source
documents; text quoted or reproduced in inputs and outputs still appears
there. Receipts are not encrypted or anonymized. Their SHA-256 digest checks
consistency, not confidentiality.

There is no maintainer-controlled retention period for locally processed
reports. You and your deployment operator control saved inputs, outputs,
receipts, and logs. Delete those copies where they are stored; deletion from
clients and providers follows their own procedures.

## Repository, external services, and contact

GitHub, package registries, model providers, and external README badges have
their own data handling policies. The M8ven badge is an external image and
link in the README; it is not runtime monitoring built into this package.
Do not submit private reports, receipts, credentials, or personal data to
public GitHub issues. Public submissions are visible to others and used to
maintain the project.

For questions about this policy, contact the maintainer through the
[GitHub repository](https://github.com/Jegoba90/anti-hallucination/issues).
Use a sanitized description; request a private contact channel before
sharing sensitive details. Changes to this policy are recorded in this
file's Git history.
