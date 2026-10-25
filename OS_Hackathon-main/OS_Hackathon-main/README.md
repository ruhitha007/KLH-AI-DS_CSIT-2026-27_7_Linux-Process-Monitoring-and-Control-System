# Mini Linux Shell with Background Job Management

A mini shell written in C using fork(), execvp() and waitpid().

## Features
- Custom prompt `mini-shell>`
- Foreground and background (`&`) execution
- `jobs`, `kill <job_id>`, `exit`
- Zombie process cleanup

## Build and run
    gcc -Wall -Wextra -o minishell minishell.c
    ./minishell
