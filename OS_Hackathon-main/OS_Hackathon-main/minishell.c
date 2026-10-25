/*
 * mini_shell_gui.c - GTK3 graphical front-end for the Mini Shell
 *
 * Install GTK (once):  sudo apt install build-essential pkg-config libgtk-3-dev
 * Compile:  gcc -Wall -Wextra -o mini_shell_gui mini_shell_gui.c $(pkg-config --cflags --libs gtk+-3.0)
 * Run:      ./mini_shell_gui
 *
 * Same core as the terminal version: fork() + execvp() + waitpid().
 * Differences for the GUI:
 *   - Command output is captured with a pipe() and shown in the text area.
 *   - Instead of a SIGCHLD handler, a timer calls waitpid(WNOHANG) every
 *     100 ms (simple and safe to mix with GTK).
 */

#define _POSIX_C_SOURCE 200809L

#include <gtk/gtk.h>
#include <glib-unix.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>

#define MAX_LINE 1024
#define MAX_ARGS 64
#define MAX_JOBS 64

/* ---------- Job table ---------- */

typedef struct {
    int    used;              /* slot in use?                           */
    int    id;                /* job ID (0 for foreground commands)     */
    pid_t  pid;
    char   cmd[MAX_LINE];
    int    background;
    int    reaped;            /* waitpid() has collected this child     */
    int    killed;            /* user pressed Kill / typed "kill"       */
    int    out_fd;            /* read end of output pipe (-1 = closed)  */
} Job;

static Job  jobs[MAX_JOBS];
static int  next_job_id = 1;
static int  fg_running  = 0;  /* a foreground command is running        */

/* ---------- Widgets ---------- */

static GtkWidget       *window, *entry, *run_btn, *kill_btn, *tree;
static GtkTextBuffer   *buffer;
static GtkTextView     *view;
static GtkListStore    *store;

/* ---------- Output area helpers ---------- */

static void append_text(const char *fmt, ...) G_GNUC_PRINTF(1, 2);
static void append_text(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    char *text = g_strdup_vprintf(fmt, ap);
    va_end(ap);

    char *valid = g_utf8_make_valid(text, -1);   /* avoid bad UTF-8 */
    GtkTextIter end;
    gtk_text_buffer_get_end_iter(buffer, &end);
    gtk_text_buffer_insert(buffer, &end, valid, -1);

    /* auto-scroll to the bottom */
    gtk_text_buffer_get_end_iter(buffer, &end);
    GtkTextMark *mark = gtk_text_buffer_create_mark(buffer, NULL, &end, FALSE);
    gtk_text_view_scroll_to_mark(view, mark, 0.0, FALSE, 0, 0);
    gtk_text_buffer_delete_mark(buffer, mark);

    g_free(valid);
    g_free(text);
}

/* Rebuild the "Background Jobs" table from the job array. */
static void refresh_job_list(void)
{
    gtk_list_store_clear(store);
    for (int i = 0; i < MAX_JOBS; i++) {
        if (jobs[i].used && jobs[i].background && !jobs[i].reaped) {
            GtkTreeIter it;
            gtk_list_store_append(store, &it);
            gtk_list_store_set(store, &it,
                               0, jobs[i].id,
                               1, (int)jobs[i].pid,
                               2, jobs[i].cmd,
                               3, "Running", -1);
        }
    }
}

static void set_busy(int busy)
{
    fg_running = busy;
    gtk_widget_set_sensitive(entry, !busy);
    gtk_widget_set_sensitive(run_btn, !busy);
    if (!busy)
        gtk_widget_grab_focus(entry);
}

/* ---------- Reading command output from the pipe ---------- */

static gboolean on_output(gint fd, GIOCondition cond, gpointer data)
{
    (void)cond;
    Job *j = data;
    char buf[1024];
    ssize_t n = read(fd, buf, sizeof(buf) - 1);

    if (n > 0) {
        buf[n] = '\0';
        append_text("%s", buf);
        return G_SOURCE_CONTINUE;
    }
    close(fd);                 /* EOF: the command closed its output */
    j->out_fd = -1;
    return G_SOURCE_REMOVE;
}

/* ---------- Timer: reap finished children (no zombies) ---------- */

static gboolean poll_jobs(gpointer data)
{
    (void)data;
    int changed = 0;

    for (int i = 0; i < MAX_JOBS; i++) {
        Job *j = &jobs[i];
        if (!j->used)
            continue;

        if (!j->reaped) {
            int status;
            pid_t r = waitpid(j->pid, &status, WNOHANG);   /* non-blocking */
            if (r == j->pid) {
                j->reaped = 1;
                changed = 1;
                if (j->background) {
                    append_text("[%d] %s  (PID %d)  %s\n", j->id,
                                j->killed ? "Terminated" : "Done",
                                (int)j->pid, j->cmd);
                }
            }
        }

        /* free the slot only when reaped AND all output has been read */
        if (j->reaped && j->out_fd < 0) {
            if (!j->background)
                set_busy(0);
            j->used = 0;
        }
    }

    if (changed)
        refresh_job_list();
    return G_SOURCE_CONTINUE;
}

/* ---------- Launching an external command ---------- */

static void launch(char *argv[], int background, const char *cmdtext)
{
    int slot = -1;
    for (int i = 0; i < MAX_JOBS; i++)
        if (!jobs[i].used) { slot = i; break; }
    if (slot < 0) {
        append_text("mini-shell: job table full\n");
        return;
    }

    int p[2];
    if (pipe(p) == -1) {
        append_text("mini-shell: pipe: %s\n", strerror(errno));
        return;
    }

    pid_t pid = fork();
    if (pid < 0) {
        append_text("mini-shell: fork: %s\n", strerror(errno));
        close(p[0]); close(p[1]);
        return;
    }

    if (pid == 0) {                              /* ---- CHILD ---- */
        close(p[0]);
        dup2(p[1], STDOUT_FILENO);               /* stdout -> pipe */
        dup2(p[1], STDERR_FILENO);               /* stderr -> pipe */
        close(p[1]);
        int devnull = open("/dev/null", O_RDONLY);
        if (devnull >= 0) {                      /* stdin -> /dev/null */
            dup2(devnull, STDIN_FILENO);
            close(devnull);
        }
        execvp(argv[0], argv);

        if (errno == ENOENT)
            fprintf(stderr, "mini-shell: command not found: %s\n", argv[0]);
        else
            fprintf(stderr, "mini-shell: %s: %s\n", argv[0], strerror(errno));
        _exit(127);
    }

    /* ---- PARENT ---- */
    close(p[1]);

    Job *j = &jobs[slot];
    memset(j, 0, sizeof(*j));
    j->used       = 1;
    j->pid        = pid;
    j->background = background;
    j->out_fd     = p[0];
    j->id         = background ? next_job_id++ : 0;
    g_strlcpy(j->cmd, cmdtext, sizeof(j->cmd));

    g_unix_fd_add(p[0], G_IO_IN | G_IO_HUP, on_output, j);

    if (background) {
        append_text("[%d] %d\n", j->id, (int)pid);
        refresh_job_list();
    } else {
        set_busy(1);      /* wait for it (GUI stays responsive) */
    }
}

/* ---------- Built-in commands ---------- */

static void do_jobs(void)
{
    int count = 0;
    for (int i = 0; i < MAX_JOBS; i++) {
        if (jobs[i].used && jobs[i].background && !jobs[i].reaped) {
            append_text("[%d] Running  PID=%d  %s\n",
                        jobs[i].id, (int)jobs[i].pid, jobs[i].cmd);
            count++;
        }
    }
    if (count == 0)
        append_text("No running background jobs.\n");
}

static void do_kill(long id)
{
    for (int i = 0; i < MAX_JOBS; i++) {
        Job *j = &jobs[i];
        if (j->used && j->background && !j->reaped && j->id == id) {
            j->killed = 1;
            if (kill(j->pid, SIGTERM) == -1)
                append_text("kill: %s\n", strerror(errno));
            else
                append_text("Sent SIGTERM to job [%ld] (PID %d)\n",
                            id, (int)j->pid);
            return;
        }
    }
    append_text("kill: no such running job: %ld\n", id);
}

static void kill_all_jobs(void)
{
    for (int i = 0; i < MAX_JOBS; i++) {
        if (jobs[i].used && !jobs[i].reaped) {
            kill(jobs[i].pid, SIGTERM);
            waitpid(jobs[i].pid, NULL, 0);
            jobs[i].reaped = 1;
        }
    }
}

/* ---------- Parse and run one command line ---------- */

static void execute_line(const char *input)
{
    char line[MAX_LINE];
    g_strlcpy(line, input, sizeof(line));
    g_strstrip(line);
    size_t len = strlen(line);
    if (len == 0)
        return;

    append_text("mini-shell> %s\n", line);

    int background = 0;
    if (line[len - 1] == '&') {
        background = 1;
        line[len - 1] = '\0';
        g_strstrip(line);
        if (line[0] == '\0') {
            append_text("mini-shell: syntax error near '&'\n");
            return;
        }
    }

    char cmdtext[MAX_LINE];
    g_strlcpy(cmdtext, line, sizeof(cmdtext));

    char *argv[MAX_ARGS];
    int argc = 0;
    for (char *t = strtok(line, " \t"); t && argc < MAX_ARGS - 1;
         t = strtok(NULL, " \t"))
        argv[argc++] = t;
    argv[argc] = NULL;

    if (strcmp(argv[0], "exit") == 0) {
        gtk_widget_destroy(window);              /* triggers cleanup */
    } else if (strcmp(argv[0], "jobs") == 0) {
        do_jobs();
    } else if (strcmp(argv[0], "clear") == 0) {
        gtk_text_buffer_set_text(buffer, "", -1);
    } else if (strcmp(argv[0], "kill") == 0) {
        const char *a = argv[1];
        if (!a) {
            append_text("Usage: kill <job_id>\n");
        } else {
            if (a[0] == '%') a++;
            char *end;
            long id = strtol(a, &end, 10);
            if (*a == '\0' || *end != '\0')
                append_text("kill: '%s' is not a valid job ID\n", a);
            else
                do_kill(id);
        }
    } else if (strcmp(argv[0], "cd") == 0) {
        const char *dir = argv[1] ? argv[1] : getenv("HOME");
        if (dir == NULL || chdir(dir) == -1)
            append_text("cd: %s\n", strerror(errno));
    } else {
        launch(argv, background, cmdtext);
    }
}

/* ---------- GUI callbacks ---------- */

static void on_run(GtkWidget *w, gpointer data)
{
    (void)w; (void)data;
    char *text = g_strdup(gtk_entry_get_text(GTK_ENTRY(entry)));
    gtk_entry_set_text(GTK_ENTRY(entry), "");
    execute_line(text);
    g_free(text);
}

static void on_kill_clicked(GtkWidget *w, gpointer data)
{
    (void)w; (void)data;
    GtkTreeSelection *sel = gtk_tree_view_get_selection(GTK_TREE_VIEW(tree));
    GtkTreeModel *model;
    GtkTreeIter it;
    if (gtk_tree_selection_get_selected(sel, &model, &it)) {
        int id;
        gtk_tree_model_get(model, &it, 0, &id, -1);
        do_kill(id);
    } else {
        append_text("Select a job in the list first.\n");
    }
}

static void on_destroy(GtkWidget *w, gpointer data)
{
    (void)w; (void)data;
    kill_all_jobs();
    gtk_main_quit();
}

/* ---------- Build the window ---------- */

static void add_column(const char *title, int col, int expand)
{
    GtkCellRenderer *r = gtk_cell_renderer_text_new();
    GtkTreeViewColumn *c =
        gtk_tree_view_column_new_with_attributes(title, r, "text", col, NULL);
    gtk_tree_view_column_set_expand(c, expand);
    gtk_tree_view_append_column(GTK_TREE_VIEW(tree), c);
}

int main(int argc, char *argv[])
{
    gtk_init(&argc, &argv);
    signal(SIGPIPE, SIG_IGN);

    for (int i = 0; i < MAX_JOBS; i++)
        jobs[i].out_fd = -1;

    /* Terminal-style look */
    GtkCssProvider *css = gtk_css_provider_new();
    gtk_css_provider_load_from_data(css,
        "textview, textview text { background-color: #1e1e1e; color: #d4d4d4;"
        "  font-family: monospace; font-size: 11pt; }"
        "#prompt { font-family: monospace; font-weight: bold; color: #2e9e4f; }",
        -1, NULL);
    gtk_style_context_add_provider_for_screen(gdk_screen_get_default(),
        GTK_STYLE_PROVIDER(css), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);

    window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(window), "Mini Shell - Background Job Manager");
    gtk_window_set_default_size(GTK_WINDOW(window), 760, 560);
    gtk_container_set_border_width(GTK_CONTAINER(window), 8);
    g_signal_connect(window, "destroy", G_CALLBACK(on_destroy), NULL);

    GtkWidget *vbox = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
    gtk_container_add(GTK_CONTAINER(window), vbox);

    /* Output area */
    GtkWidget *tv = gtk_text_view_new();
    view = GTK_TEXT_VIEW(tv);
    gtk_text_view_set_editable(view, FALSE);
    gtk_text_view_set_cursor_visible(view, FALSE);
    gtk_text_view_set_wrap_mode(view, GTK_WRAP_WORD_CHAR);
    gtk_text_view_set_left_margin(view, 6);
    buffer = gtk_text_view_get_buffer(view);
    GtkWidget *sw = gtk_scrolled_window_new(NULL, NULL);
    gtk_container_add(GTK_CONTAINER(sw), tv);
    gtk_box_pack_start(GTK_BOX(vbox), sw, TRUE, TRUE, 0);

    /* Command row: prompt + entry + Run */
    GtkWidget *hbox = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    GtkWidget *prompt = gtk_label_new("mini-shell>");
    gtk_widget_set_name(prompt, "prompt");
    entry = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(entry),
        "type a command, e.g.  sleep 30 &   (Enter to run)");
    run_btn = gtk_button_new_with_label("Run");
    gtk_box_pack_start(GTK_BOX(hbox), prompt, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(hbox), entry, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(hbox), run_btn, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(vbox), hbox, FALSE, FALSE, 0);
    g_signal_connect(entry, "activate", G_CALLBACK(on_run), NULL);
    g_signal_connect(run_btn, "clicked", G_CALLBACK(on_run), NULL);

    /* Background jobs panel */
    GtkWidget *frame = gtk_frame_new("Background Jobs");
    GtkWidget *fbox = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
    gtk_container_set_border_width(GTK_CONTAINER(fbox), 6);
    gtk_container_add(GTK_CONTAINER(frame), fbox);

    store = gtk_list_store_new(4, G_TYPE_INT, G_TYPE_INT,
                               G_TYPE_STRING, G_TYPE_STRING);
    tree = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store));
    add_column("Job ID", 0, 0);
    add_column("PID", 1, 0);
    add_column("Command", 2, 1);
    add_column("Status", 3, 0);
    GtkWidget *tsw = gtk_scrolled_window_new(NULL, NULL);
    gtk_widget_set_size_request(tsw, -1, 130);
    gtk_container_add(GTK_CONTAINER(tsw), tree);
    gtk_box_pack_start(GTK_BOX(fbox), tsw, TRUE, TRUE, 0);

    kill_btn = gtk_button_new_with_label("Kill Selected Job");
    gtk_widget_set_halign(kill_btn, GTK_ALIGN_END);
    gtk_box_pack_start(GTK_BOX(fbox), kill_btn, FALSE, FALSE, 0);
    g_signal_connect(kill_btn, "clicked", G_CALLBACK(on_kill_clicked), NULL);

    gtk_box_pack_start(GTK_BOX(vbox), frame, FALSE, FALSE, 0);

    append_text("Welcome to Mini Shell GUI.\n"
                "Commands: any Linux command, 'cmd &' for background, "
                "jobs, kill <job_id>, cd, clear, exit\n\n");

    g_timeout_add(100, poll_jobs, NULL);   /* reap children every 100 ms */

    gtk_widget_show_all(window);
    gtk_widget_grab_focus(entry);
    gtk_main();
    return 0;
}
