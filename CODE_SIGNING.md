# Code signing policy

**Windows releases are not code-signed at present.** Windows SmartScreen warns about the
installer when it is downloaded and first run, and *More info > Run anyway* goes past it.
Where an unsigned program is a problem, install from [PyPI](https://pypi.org/project/pyflashgui/)
with `pip install pyflashgui` instead: SmartScreen does not apply to it.

Signing is intended. The plan is SignPath Foundation's free code signing for open-source
projects, which asks for an established user base first, so it will be applied for once
pyflashgui has one. This page says how releases will be signed, and will say from which release
they are.

## What will be signed

The Windows build attached to each [release](https://github.com/davhodg/pyflashgui/releases):

- `pyflashgui.exe`, the application, signed before it is packaged; and
- `pyflashgui-<version>-setup.exe`, the installer that carries it.

Both are built by this repository's GitHub Actions workflow
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) from the tagged commit, and will be
sent for signing from that workflow. Nothing built anywhere else is to be submitted for
signing. The workflow has the signing steps in place already, switched off until there is a
signing service to use.

Meanwhile every release installer carries a **build attestation**: GitHub signs, with
[Sigstore](https://www.sigstore.dev/), a record that the file was built by this workflow from
the tagged commit, and keeps it in a public log. To check a download:

```
gh attestation verify pyflashgui-<version>-setup.exe --repo davhodg/pyflashgui
```

That says where a file came from. It is not an Authenticode signature, so Windows does not read
it and SmartScreen still warns.

The other files in the build -- Python, Qt and the libraries pyflashgui uses -- are other
projects' work and are not signed by this project; they are listed in
`THIRD-PARTY-NOTICES.txt`. The packages on [PyPI](https://pypi.org/project/pyflashgui/) are not
code-signed; PyPI carries attestations of the workflow that built them instead.

## Team roles

pyflashgui has one maintainer, who holds every role, and uses multi-factor authentication for
the repository on GitHub and for the project on SignPath.io:

| Role | Members |
|---|---|
| Authors -- write the source | [davhodg](https://github.com/davhodg) |
| Committers -- can change this repository | [davhodg](https://github.com/davhodg) |
| Reviewers -- review every change from someone else before it is merged | [davhodg](https://github.com/davhodg) |
| Approvers -- approve each signing request | [davhodg](https://github.com/davhodg) |

Contributions from anyone else come as pull requests, reviewed before they are merged; see
[CONTRIBUTING.md](CONTRIBUTING.md), and the [code of conduct](CODE_OF_CONDUCT.md). A release is
made by the maintainer pushing a version tag, and once releases are signed, each signing
request it raises is approved by an approver before anything is signed.

## Privacy policy

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it.

In practice that means three things, each asked for: *Help > Check for updates* (which asks
GitHub, or PyPI for a pip installation, for the latest version), opening a web page you chose,
and downloading a CMSIS-Pack for a target after you ask for one. [SECURITY.md](SECURITY.md)
lists them too, and treats pyflashgui going online when you did not ask it to as a fault to
report.

pyflashgui talks to debug probes and the device a probe is connected to, which is what it is
for; that is not a networked system in this sense, and nothing read from one is sent anywhere
else.

The services those three contact have privacy policies of their own: GitHub's
[Privacy Statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement)
for checking for updates to the installed build or a source folder, and the Python Software
Foundation's [Privacy Notice](https://policies.python.org/python.org/Privacy-Notice/) for PyPI,
for checking for updates to a pip installation. CMSIS-Packs come from the pack's own
publisher, through the Open-CMSIS-Pack index.

## Changes to the system, and uninstalling

The installer says what it will do before it does it: a desktop shortcut is a task shown, and
can be unticked, before anything is installed. It installs an uninstaller, which takes away
the program and its shortcuts.

Inside pyflashgui, a Start menu entry for a source folder is added only when asked for. The
[README](README.md#uninstalling) says how to uninstall each way of installing pyflashgui.
Your own files -- workspaces and their settings -- are never removed by uninstalling, and the
README says where they are.
