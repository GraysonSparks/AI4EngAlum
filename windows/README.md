# Running the assistant on the Windows laptop

The same assistant as on the Linux desktop, with the same versions: Python 3.12.14, the package
versions in `rag/requirements-windows.txt`, Ollama 0.40.6, and the same `qwen3.5:9b` and
`nomic-embed-text` builds (setup checks their digests). Written for the Lenovo Legion Pro 5
16IAX10, RTX 5070 Laptop (8 GB), Windows 11.

## Getting the code onto the laptop

Clone the repo (`git clone https://github.com/GraysonSparks/AI4EngAlum.git`) or unzip a copy of it.
Nothing the scripts create goes into the project folder: the Python environment, search index and
follow-up requests live in `%LOCALAPPDATA%\AI4EngAlum`.

## The four scripts (double-click them in `windows\`)

| Script | What it does |
|---|---|
| `Setup.bat` | Run once. Installs uv, Python 3.12.14, the packages, Ollama 0.40.6 and the models (about 7 GB), builds the index, then runs `test_contact.py`, `test_notify.py` and the 63-case `eval_models.py`. Ends with SETUP COMPLETE in green, or lists the checks that failed. Safe to run again. `Setup.bat -SkipEval` skips the eval. |
| `Start.bat` | Starts Ollama, loads the models and reports **100% GPU** for each (yellow warning if part of a model is on the CPU), starts the server, and opens http://127.0.0.1:8000/. Press **Ctrl+C** in its window to stop everything. |
| `Stop.bat` | Stops the server, unloads the models, quits Ollama, then checks no Ollama process is left. Green **STOPPED. The model is not running and its GPU memory is free.** means it is really off; red means something is still running. |
| `Status.bat` | Shows what is running right now and changes nothing. |

**Knowing the model has stopped:** Ctrl+C in the Start window runs the same steps and checks as
`Stop.bat` and ends with the green STOPPED banner. If you closed the window with the X instead, those
steps did not run: double-click `Stop.bat`. `Status.bat` shows NOTHING IS RUNNING when it is all off.

While the server runs, Ollama unloads an idle model after 5 minutes on its own (as on the desktop),
and the next question reloads it in a few seconds. `Status.bat` shows when.

## If something goes wrong

- **"running scripts is disabled" or a policy error:** the school's policy blocks PowerShell scripts
  even with `-ExecutionPolicy Bypass`. Ask OIT, or run the commands in `setup.ps1` by hand.
- **A model shows less than 100% GPU:** another program is using the 8 GB of GPU memory. Close games,
  video apps and extra browser windows, then `Stop.bat` and `Start.bat`.
- **Setup says a model is a different build than the desktop's:** the tag was updated upstream, so
  answers may differ. To match exactly, copy the model files from the desktop (`/var/lib/ollama` on
  Linux) into `%USERPROFILE%\.ollama\models` on the laptop with Ollama stopped, then run Setup again.
- **Port 8000 is in use:** run `Stop.bat`. If it says something else is using the port, close that
  program.

## After changing `rag/requirements.txt`

Regenerate the Windows pins on the desktop, from `3_Code/rag`, so both machines stay identical:

```bash
VIRTUAL_ENV=~/.local/share/venvs/ai4engalum-rag uv pip freeze > /tmp/linux-freeze.txt
{ echo "# Exact package versions for the Windows laptop, matching the Linux venv (Python 3.12.14)."
  echo "# Regenerate after changing requirements.txt: see ../windows/README.md"
  uv pip compile requirements.txt -c /tmp/linux-freeze.txt --python-platform x86_64-pc-windows-msvc \
    --python-version 3.12 --no-header --no-annotate -q; } > requirements-windows.txt
```

Then run `Setup.bat` again on the laptop.
