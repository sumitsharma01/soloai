# Working on SoloAI

## Branches and pull requests

Start from an up-to-date `main` and create a branch for the change. Keep commits focused and describe what changed. Do not commit credentials, local databases, downloaded tools or runtime logs.

Open a pull request with the problem, the resulting behavior and the checks you ran. State any checks you could not run. Wait for CI before merging. Use a merge commit when the branch contains useful, separate commits; squash a branch when its history is mostly work in progress. Do not force-push `main` or bypass required checks.

After merging, update your local `main`. Keep a feature branch until its changes are confirmed on `main`.

## Writing

Write for the person who has to use or maintain the feature. Explain what works, what to do next and what can go wrong.

- Use ordinary words and short, direct sentences.
- Lead with the result or the task. Put background after it.
- Use concrete examples and commands that someone can follow.
- Explain technical terms when the reader needs them.
- Avoid marketing claims, filler, em dashes and phrases such as “seamless integration” or “robust solution.”
- Say what was tested and what the result establishes. A mocked test is not a live integration test.
- Keep known failures visible. Do not describe a pilot as production-ready.
- Give each guide one purpose. Link to another guide instead of repeating it.

These rules apply to README files, runbooks, reports, release notes and pull request descriptions. Machine-readable evaluation reports should keep their stable field names; explain them in the accompanying guide.

## Checks

Run `python -m pytest -q` for application changes. CI also runs the database tests against PostgreSQL, audits dependencies and builds the container. Infrastructure changes have separate Terraform checks.

Live evaluations cost money. Use synthetic cases, record the model and instructions, and keep customer content and credentials out of reports. Tests must not send real emails unless a controlled recipient and the send itself have been explicitly approved.
