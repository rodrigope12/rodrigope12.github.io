#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char exe_path[PATH_MAX];
    ssize_t len = readlink("/proc/self/exe", exe_path, sizeof(exe_path) - 1);
    if (len < 0) {
        perror("readlink");
        return 1;
    }
    exe_path[len] = '\0';

    char *last_slash = strrchr(exe_path, '/');
    if (last_slash == NULL) {
        fprintf(stderr, "No se pudo resolver la carpeta del lanzador.\n");
        return 1;
    }
    *last_slash = '\0';

    char helper_path[PATH_MAX];
    int written = snprintf(
        helper_path,
        sizeof(helper_path),
        "%s/.abrir_captura_gemini_en_terminal.sh",
        exe_path
    );
    if (written < 0 || written >= (int)sizeof(helper_path)) {
        fprintf(stderr, "La ruta del helper es demasiado larga.\n");
        return 1;
    }

    char **child_argv = calloc((size_t)argc + 2, sizeof(char *));
    if (child_argv == NULL) {
        perror("calloc");
        return 1;
    }

    child_argv[0] = "bash";
    child_argv[1] = helper_path;
    for (int i = 1; i < argc; ++i) {
        child_argv[i + 1] = argv[i];
    }
    child_argv[argc + 1] = NULL;

    execv("/bin/bash", child_argv);
    perror("execv");
    free(child_argv);
    return errno == 0 ? 1 : errno;
}
