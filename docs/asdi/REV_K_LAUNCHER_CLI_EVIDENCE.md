# REV K Launcher CLI Evidence

**Date:** 2026-11-16  
**Result:** **Local prototype PASS**

`launcher/cli.py` provides durable REV K operations:

```sh
run --contract CONTRACT
status --run-id RUN_ID
list
kill --run-id RUN_ID
governance --window-days 7
```

`run` persists a launcher state file before execution and the terminal result/evidence afterward. `status`, `list`, and `kill` read that durable file. `kill` sends SIGTERM to the saved process and kills the recorded container, then marks the run `killed`.

Mocked-runtime tests prove successful run persistence, status retrieval, container kill, and durable killed state.
