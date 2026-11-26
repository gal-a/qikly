# Open source tools that find test gaps and bugs in your Python code

More and more code is written with the help of AI, and it ships faster than anyone can read it. That makes the safety net around the code matter more: tests that really check behaviour, and tools that catch what the tests and the author missed. A tool that finds even one critical bug before it escalates is worth installing, and every tool below is open source and works on Python.

This page is a community list. It helps anyone who wants to make Python software more robust to find the right tool for the job.

**Know a tool that belongs here?** Add it with a one-row pull request: see [how to add a tool](#how-to-add-a-tool).

**Disclosure:** this page lives in the repository of [qikly](https://github.com/gal-a/qikly), which is listed below like any other tool. qikly is written by the maintainer of this repository.

**Found a mistake?** Please [let me know](https://github.com/gal-a/qikly/issues/new), or send a pull request with the fix. Licences, limits and maintenance status change, and I check them by hand.

## How to read the tables

- **Licence and cost:** the licence of the tool's source code, linked from the tool's own repository. "Free" means no fee for the tool itself. Where the tool calls a language model, you pay your own model provider, and the row says so.
- **LLM:** whether the tool uses a large language model. "Optional" means it works without one.
- **Last commit:** a live badge from the tool's repository, so you can see whether it is still maintained.
- The tables list what a tool is for, not how good it is. Try two or three on one module of your own code.

## 1. Check how good your tests are (mutation testing and coverage)

Mutation tools plant small faults in a copy of your code and run your tests. A fault that no test notices shows a gap in the tests. Coverage tools show which lines ran, but not whether a test would notice a change in them.

| Tool | Finds | Licence and cost | LLM | Last commit |
|---|---|---|---|---|
| [qikly](https://github.com/gal-a/qikly) (`--score`) | Plants faults in a copy of your code and reports the ones your tests miss | Free (Apache-2.0) | No: this step makes no model call and needs no key | ![last commit](https://img.shields.io/github/last-commit/gal-a/qikly?style=for-the-badge) |
| [Cosmic Ray](https://github.com/sixty-north/cosmic-ray) | Faults your tests miss | Free (MIT) | No | ![last commit](https://img.shields.io/github/last-commit/sixty-north/cosmic-ray?style=for-the-badge) |
| [coverage.py](https://github.com/coveragepy/coveragepy) | Lines your tests never run | Free (Apache-2.0) | No | ![last commit](https://img.shields.io/github/last-commit/coveragepy/coveragepy?style=for-the-badge) |
| [Mutahunter](https://github.com/codeintegrity-ai/mutahunter) | Faults your tests miss, planted by an LLM. Its README calls it language agnostic | Free (AGPL-3.0), you pay your LLM provider | Yes | ![last commit](https://img.shields.io/github/last-commit/codeintegrity-ai/mutahunter?style=for-the-badge) |
| [mutmut](https://github.com/boxed/mutmut) | Faults your tests miss | Free (BSD-3-Clause) | No | ![last commit](https://img.shields.io/github/last-commit/boxed/mutmut?style=for-the-badge) |

## 2. Write tests for you

| Tool | What it does | Licence and cost | LLM | Last commit |
|---|---|---|---|---|
| [qikly](https://github.com/gal-a/qikly) (`--tasks`, `--fresh`) | Writes functional tests from a spec, without seeing the code. Unit tests are written last, with the code in view | Free (Apache-2.0), you pay your LLM provider | Yes | ![last commit](https://img.shields.io/github/last-commit/gal-a/qikly?style=for-the-badge) |
| [Pynguin](https://github.com/se2p/pynguin) | Generates unit tests by search | Free (MIT) | Optional: the source has an LLM-based mode | ![last commit](https://img.shields.io/github/last-commit/se2p/pynguin?style=for-the-badge) |
| [Qodo Cover](https://github.com/qodo-ai/qodo-cover) | Generates tests with an LLM. Its README describes Python projects | Free (AGPL-3.0), you pay your LLM provider. **The repository says it is no longer maintained** | Yes | ![last commit](https://img.shields.io/github/last-commit/qodo-ai/qodo-cover?style=for-the-badge) |

## 3. Find bugs by running your code

| Tool | Finds | Licence and cost | LLM | Last commit |
|---|---|---|---|---|
| [qikly](https://github.com/gal-a/qikly) (`--tasks`) | Bugs found indirectly: it writes tests from the spec without seeing the code, and a test that fails on the code points at a bug or a gap in the spec | Free (Apache-2.0), you pay your LLM provider | Yes, with your own Gemini, OpenAI or Anthropic key | ![last commit](https://img.shields.io/github/last-commit/gal-a/qikly?style=for-the-badge) |
| [Atheris](https://github.com/google/atheris) | Crashes found by coverage-guided fuzzing | Free (Apache-2.0) | No | ![last commit](https://img.shields.io/github/last-commit/google/atheris?style=for-the-badge) |
| [CrossHair](https://github.com/pschanely/CrossHair) | Inputs that break a contract or type hints, found by symbolic execution | Free (MIT, with some Apache and PSF parts) | No | ![last commit](https://img.shields.io/github/last-commit/pschanely/CrossHair?style=for-the-badge) |
| [Hypothesis](https://hypothesis.works) | Inputs that break a stated property | Free (MPL-2.0) | No | ![last commit](https://img.shields.io/github/last-commit/HypothesisWorks/hypothesis?style=for-the-badge) |
| [OSS-Fuzz](https://github.com/google/oss-fuzz) | Continuous fuzzing for open source projects, including Python ones ([guide](https://github.com/google/oss-fuzz/blob/master/docs/getting-started/new-project-guide/python_lang.md)) | Free for projects that are accepted (Apache-2.0) | No | ![last commit](https://img.shields.io/github/last-commit/google/oss-fuzz?style=for-the-badge) |
| [Schemathesis](https://github.com/schemathesis/schemathesis) | Crashes and spec violations in APIs, from their OpenAPI or GraphQL schema. It is written in Python and tests an API in any language | Free (MIT) | No | ![last commit](https://img.shields.io/github/last-commit/schemathesis/schemathesis?style=for-the-badge) |

## 4. Read your code for bugs and vulnerabilities (static analysis)

These tools read the code without running it. qikly is not one of them.

| Tool | Finds | Licence and cost | LLM | Last commit |
|---|---|---|---|---|
| [Bandit](https://github.com/PyCQA/bandit) | Common security mistakes | Free (Apache-2.0) | No | ![last commit](https://img.shields.io/github/last-commit/PyCQA/bandit?style=for-the-badge) |
| [mypy](https://github.com/python/mypy) | Type errors | Free (MIT) | No | ![last commit](https://img.shields.io/github/last-commit/python/mypy?style=for-the-badge) |
| [Ruff](https://docs.astral.sh/ruff/) | Lint errors and style problems, very fast | Free (MIT) | No | ![last commit](https://img.shields.io/github/last-commit/astral-sh/ruff?style=for-the-badge) |
| [Semgrep](https://github.com/semgrep/semgrep) (the open source engine) | Bugs and vulnerabilities, with rules you can write. It lists Python among its languages | Free (LGPL-2.1). The vendor's hosted platform is a separate, commercial product and is not listed | No | ![last commit](https://img.shields.io/github/last-commit/semgrep/semgrep?style=for-the-badge) |
| [SonarQube Community Build](https://github.com/SonarSource/sonarqube) | Bugs, code smells and vulnerabilities, with [Python analysis](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/languages/python) | Free (LGPL-3.0). The vendor's hosted and paid editions are separate products and are not listed | No | ![last commit](https://img.shields.io/github/last-commit/SonarSource/sonarqube?style=for-the-badge) |

## 5. AI review of pull requests

| Tool | What it does | Licence and cost | LLM | Last commit |
|---|---|---|---|---|
| [PR-Agent](https://github.com/The-PR-Agent/pr-agent) | Reviews pull requests. A community-maintained project, originally from Qodo. Its README names no language, so check that it suits your code | Free (MIT) | Yes | ![last commit](https://img.shields.io/github/last-commit/The-PR-Agent/pr-agent?style=for-the-badge) |

## How to add a tool

Anyone can add a tool with a small pull request. It takes one row.

1. Fork this repository and edit this file, [docs/tools.md](https://github.com/gal-a/qikly/blob/main/docs/tools.md).
2. Add one row to the table where the tool fits. Keep each table in alphabetical order, except that qikly stays on top (the order is a judgement call, so ask if unsure).
3. Fill every column. Write the licence as its SPDX name, such as MIT or Apache-2.0, in the "Licence and cost" column, and **Yes**, **No** or **Optional** in the LLM column. Copy the "Last commit" badge from another row and change the repository name.
4. Link the tool's repository, so the licence can be checked in its LICENSE file.
5. Describe the PR with your relationship to the tool (user, author, employee). Authors are welcome to add their own tool, and must say so.

**Inclusion rules**

- The tool must work on Python code, or find bugs in a Python program. A tool for other languages only is not listed on this page.
- The tool must be open source under an OSI-approved licence, so anyone can read it and check what it does. Commercial and source-available products are not listed.
- The tool must help find test gaps or bugs in code.
- It must be real and usable today. A repository that says it is no longer maintained can stay listed, with that written in the row.
- Claims must be checkable. No benchmarks or "best" without a link to the data.
- Competing tools are welcome. This list is for the reader, not for any one tool.

To correct a wrong fact (a licence changed, a project stopped being maintained), open a pull request or an [issue](https://github.com/gal-a/qikly/issues/new) with the link to the repository.

*Last checked: 2026-11-26.*
