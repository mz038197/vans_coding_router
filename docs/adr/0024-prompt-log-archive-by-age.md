# Prompt Log archive follows Archive Age

A Prompt Log stays on the teacher conversation list after its Class ends, until Archive Age, counting from when that log was created. Ending a Class does not archive it. A Prompt Log Archive does not return to that list, including logs already archived while still younger than Archive Age. The teacher list does not show archived conversations. The conversation text stays until Delete Age.

Production moves due logs inside Postgres, a small committed batch at a time, until none remain. That move does not load conversation text into the router process. Loading every due log at startup exhausted the 1 GB machine and the kernel killed `uvicorn`. The local SQLite archive is a separate year file, so that path copies one small batch of rows at a time.

## Considered Options

- **Archive every log when the Class ends**: rejected. A teacher can still read a Prompt Log after the Class ends, until Archive Age. That rule also pulled an entire ended class into memory on the next process start.
- **Restore young logs that were archived only because the Class had ended**: rejected. Archive does not return a log to the teacher list.
- **Show the Prompt Log Archive on the teacher conversation list until Delete Age**: rejected. Archive Age is when the log leaves that list.
- **Read every due conversation into the router, then copy it**: rejected. The backlog is larger than the machine.
